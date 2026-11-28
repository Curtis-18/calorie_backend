"""Asking Gemini for one coach reply, and checking it before it is shown."""

import logging
from collections.abc import AsyncIterator
from contextlib import aclosing

from app.services import coach_prompt
from app.services.gemini_client import generate_content, stream_content
from app.i18n import t

log = logging.getLogger("calorie_backend")

HISTORY_TURNS = 10
MAX_ATTEMPTS = 2  # one try, and one more when the first reply broke a rule

# Room for Gemini's answer. Until 28 Nov 2026 this was 600, and replies were cut
# off mid-sentence (the owner: "sometimes its answers cut off mid sentence"):
# the limit also counts the model's thinking ("the maximum number of tokens a
# response can generate, including thought tokens", Google's thinking docs),
# and the prompt asks for at most about 150 words. The free quota counts
# requests, not tokens, so the larger limit costs nothing there.
MAX_OUTPUT_TOKENS = 2048

# Gemini's reasons for stopping because the limit was reached.
CUT_OFF = {"MAX_TOKENS", "CONTINUATION"}


class CoachUnavailable(Exception):
    """Gemini could not be reached or answered with nothing usable."""


def _history_contents(history: list[tuple[str, str]]) -> list[dict]:
    """The last turns as Gemini contents, starting with a person's turn."""
    turns = list(history)[-HISTORY_TURNS:]
    while turns and turns[0][0] != "user":
        turns.pop(0)
    out = []
    for role, body in turns:
        if role == "user":
            out.append({"role": "user", "parts": [{"text": coach_prompt.wrap_user_text(body)}]})
        else:
            out.append({"role": "model", "parts": [{"text": body}]})
    return out


def _payload(*, context: str, history: list[tuple[str, str]], text: str, lang: str) -> dict:
    contents = _history_contents(history) + [
        {"role": "user", "parts": [{"text": coach_prompt.wrap_user_text(text)}]}
    ]
    return {
        "system_instruction": {"parts": [{"text": coach_prompt.system_prompt(context, lang)}]},
        "contents": contents,
        "generationConfig": {"temperature": 0.6, "maxOutputTokens": MAX_OUTPUT_TOKENS},
    }


def _raw_text(data: dict) -> str:
    """The answer's text in this response (or streamed piece), unstripped;
    thinking parts, if any were ever sent, are left out."""
    candidates = data.get("candidates") or []
    if not candidates:
        return ""
    parts = (candidates[0].get("content") or {}).get("parts") or []
    return "".join(p.get("text", "") for p in parts if p.get("text") and not p.get("thought"))


def _text_of(data: dict) -> str:
    return _raw_text(data).strip()


def _finish_reason(data: dict) -> str | None:
    candidates = data.get("candidates") or []
    return (candidates[0].get("finishReason") if candidates else None) or None


def _finished(reply: str, reason: str | None, usage: dict) -> str:
    """The reply as it may be shown: cut back to its last full sentence when
    Gemini stopped at the length limit (logged with the thinking it used, so
    the limit can be checked in the Render log)."""
    if reason in CUT_OFF:
        log.warning("coach reply cut at the limit: reason=%s output_tokens=%s thought_tokens=%s",
                    reason, usage.get("candidatesTokenCount", "?"), usage.get("thoughtsTokenCount", 0))
        return coach_prompt.trim_to_sentence(reply)
    return reply


def _count(usage: dict) -> tuple[int, int]:
    return int(usage.get("promptTokenCount") or 0), int(usage.get("candidatesTokenCount") or 0)


async def reply_to(
    *, context: str, history: list[tuple[str, str]], text: str, lang: str, floor: int
) -> tuple[str, int, int, bool]:
    """(reply, tokens_in, tokens_out, from_model).

    A reply that breaks a rule is asked for once more; if that breaks one too,
    a fixed kind sentence is returned instead (from_model False). Raises
    CoachUnavailable when Gemini fails, so nothing is stored and a retry with
    the same id simply asks again.
    """
    payload = _payload(context=context, history=history, text=text, lang=lang)
    tokens_in = tokens_out = 0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            data = await generate_content(payload, kind="coach")
        except Exception as exc:  # noqa: BLE001
            log.warning("coach call failed: %r", exc)
            raise CoachUnavailable() from exc
        usage = data.get("usageMetadata") or {}
        used_in, used_out = _count(usage)
        tokens_in, tokens_out = tokens_in + used_in, tokens_out + used_out
        reply = _finished(_text_of(data), _finish_reason(data), usage)
        problem = coach_prompt.reply_problem(reply, floor)
        if problem is None:
            return reply, tokens_in, tokens_out, True
        # The reason only, never the reply or the person's words.
        log.info("coach reply rejected (attempt %d/%d): %s", attempt, MAX_ATTEMPTS, problem.split(":")[0])
    return t(lang, coach_prompt.SAFE_FALLBACK), tokens_in, tokens_out, False


# What stream_reply yields: ("delta", text) is checked text to show next;
# ("reset", None) means drop what was shown, a new answer follows;
# ("final", (reply, tokens_in, tokens_out, from_model)) ends it. The final
# reply is the whole answer as stored, and it is what the app keeps: the
# deltas only let it start typing sooner (the last sentence, an answer cut
# back at the length limit, or a second attempt arrive only in the final).
Event = tuple[str, object]


async def stream_reply(
    *, context: str, history: list[tuple[str, str]], text: str, lang: str, floor: int
) -> AsyncIterator[Event]:
    """Like reply_to, but passes the answer on while Gemini writes it.

    Only finished sentences are passed on, and only after everything up to
    them has passed the same check as a whole reply (reply_problem), so the
    person never sees a line the check would stop. If a later sentence breaks
    a rule, a "reset" follows and the second attempt is asked for in one piece,
    exactly as in reply_to. Raises CoachUnavailable when Gemini fails; if that
    happens after some text was passed on, the caller tells the app, which
    asks again with the same id through POST /coach/messages.
    """
    payload = _payload(context=context, history=history, text=text, lang=lang)
    buffer, shown, reason, usage = "", 0, None, {}
    problem = None
    try:
        async with aclosing(stream_content(payload, kind="coach")) as chunks:
            async for chunk in chunks:
                buffer += _raw_text(chunk)
                reason = _finish_reason(chunk) or reason
                usage = chunk.get("usageMetadata") or usage
                cut = coach_prompt.release_point(buffer)
                if cut <= shown:
                    continue
                problem = coach_prompt.reply_problem(buffer[:cut], floor)
                if problem is not None:
                    break  # stop listening: the rest of this answer is not used
                yield "delta", buffer[shown:cut]
                shown = cut
    except Exception as exc:  # noqa: BLE001
        log.warning("coach stream failed (after %d characters): %r", shown, exc)
        raise CoachUnavailable() from exc
    tokens_in, tokens_out = _count(usage)

    if problem is None:
        reply = _finished(buffer.strip(), reason, usage)
        problem = coach_prompt.reply_problem(reply, floor)
        if problem is None:
            yield "final", (reply, tokens_in, tokens_out, True)
            return
    log.info("coach reply rejected (attempt 1/%d): %s", MAX_ATTEMPTS, problem.split(":")[0])
    if shown:
        yield "reset", None
    # The second attempt in one piece, as reply_to does it.
    try:
        data = await generate_content(payload, kind="coach")
    except Exception as exc:  # noqa: BLE001
        log.warning("coach call failed: %r", exc)
        raise CoachUnavailable() from exc
    usage = data.get("usageMetadata") or {}
    used_in, used_out = _count(usage)
    tokens_in, tokens_out = tokens_in + used_in, tokens_out + used_out
    reply = _finished(_text_of(data), _finish_reason(data), usage)
    problem = coach_prompt.reply_problem(reply, floor)
    if problem is None:
        yield "final", (reply, tokens_in, tokens_out, True)
        return
    log.info("coach reply rejected (attempt 2/%d): %s", MAX_ATTEMPTS, problem.split(":")[0])
    yield "final", (t(lang, coach_prompt.SAFE_FALLBACK), tokens_in, tokens_out, False)


def care_reply(lang: str) -> str:
    return t(lang, coach_prompt.CARE_REPLY)
