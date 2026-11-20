"""Asking Gemini for one coach reply, and checking it before it is shown."""

import logging

from app.services import coach_prompt
from app.services.gemini_client import generate_content
from app.i18n import t

log = logging.getLogger("calorie_backend")

HISTORY_TURNS = 10
MAX_ATTEMPTS = 2  # one try, and one more when the first reply broke a rule


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


def _text_of(data: dict) -> str:
    candidates = data.get("candidates") or []
    if not candidates:
        return ""
    parts = (candidates[0].get("content") or {}).get("parts") or []
    return "".join(p.get("text", "") for p in parts if p.get("text")).strip()


async def reply_to(
    *, context: str, history: list[tuple[str, str]], text: str, lang: str, floor: int
) -> tuple[str, int, int, bool]:
    """(reply, tokens_in, tokens_out, from_model).

    A reply that breaks a rule is asked for once more; if that breaks one too,
    a fixed kind sentence is returned instead (from_model False). Raises
    CoachUnavailable when Gemini fails, so nothing is stored and a retry with
    the same id simply asks again.
    """
    contents = _history_contents(history) + [
        {"role": "user", "parts": [{"text": coach_prompt.wrap_user_text(text)}]}
    ]
    payload = {
        "system_instruction": {"parts": [{"text": coach_prompt.system_prompt(context, lang)}]},
        "contents": contents,
        "generationConfig": {"temperature": 0.6, "maxOutputTokens": 600},
    }
    tokens_in = tokens_out = 0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            data = await generate_content(payload, kind="coach")
        except Exception as exc:  # noqa: BLE001
            log.warning("coach call failed: %r", exc)
            raise CoachUnavailable() from exc
        usage = data.get("usageMetadata") or {}
        tokens_in += int(usage.get("promptTokenCount") or 0)
        tokens_out += int(usage.get("candidatesTokenCount") or 0)
        reply = _text_of(data)
        problem = coach_prompt.reply_problem(reply, floor)
        if problem is None:
            return reply, tokens_in, tokens_out, True
        # The reason only, never the reply or the person's words.
        log.info("coach reply rejected (attempt %d/%d): %s", attempt, MAX_ATTEMPTS, problem.split(":")[0])
    return t(lang, coach_prompt.SAFE_FALLBACK), tokens_in, tokens_out, False


def care_reply(lang: str) -> str:
    return t(lang, coach_prompt.CARE_REPLY)
