import asyncio
import copy
import json
import logging
import time
from collections.abc import AsyncIterator

import httpx

from app.core.config import settings
from app.services import gemini_budget

log = logging.getLogger("calorie_backend")

# Only a 503 ("This model is currently experiencing high demand. Spikes in
# demand are usually temporary.") is worth another try: a short retry rides out
# the spike. A 429 means the quota is spent, so retrying only burns more of it;
# 500/502/504 are not retried either, so one bad request is never paid for
# three times (handover: "Gemini spend controls").
RETRYABLE_STATUSES = {503}
MAX_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 0.5

# Flash models "think" by default and those tokens are billed as output, which
# is wasted on "photo to JSON" and a short paragraph. Gemini 2.5 takes a
# budget, Gemini 3 takes a level. The right parameter for the configured model
# could not be verified against the live API, so this is fail-safe: if Gemini
# answers 400 mentioning "thinking", the call is repeated without it and it is
# not sent again until restart, so a wrong guess can't break scans.
_thinking_rejected = False


def thinking_config(model: str) -> dict | None:
    name = model.lower()
    if "gemini-2.5" in name:
        # The Pro models cannot switch thinking off; they take a small budget.
        return {"thinkingBudget": 128 if "pro" in name else 0}
    if "gemini-3" in name:
        return {"thinkingLevel": "low"}
    return None


def _with_thinking(payload: dict, model: str) -> dict:
    """A copy of [payload] asking for minimal thinking, unless the caller set
    its own or Gemini already rejected the parameter."""
    config = thinking_config(model)
    if _thinking_rejected or config is None:
        return payload
    out = copy.deepcopy(payload)
    generation = out.setdefault("generationConfig", {})
    generation.setdefault("thinkingConfig", config)
    return out


def _kind(payload: dict) -> str:
    """scan (an image is attached) or insights, for the spend log line."""
    for content in payload.get("contents") or []:
        for part in content.get("parts") or []:
            if "inline_data" in part or "inlineData" in part:
                return "scan"
    return "insights"


def _log_call(payload: dict, data: dict, attempts: int, started: float, kind: str | None = None, model: str | None = None) -> None:
    usage = data.get("usageMetadata") or {}
    log.info(
        "gemini_call kind=%s model=%s attempts=%d ms=%d prompt_tokens=%s output_tokens=%s thought_tokens=%s",
        kind or _kind(payload),
        model or settings.gemini_model,
        attempts,
        (time.monotonic() - started) * 1000,
        usage.get("promptTokenCount", "?"),
        usage.get("candidatesTokenCount", "?"),
        usage.get("thoughtsTokenCount", 0),
    )


async def generate_content(payload: dict, timeout: float = 30.0, kind: str | None = None) -> dict:
    """POST to Gemini, retrying transient failures with exponential backoff.

    [kind] names the feature for the spend log line (scan, insights, coach, ...);
    when omitted it is inferred from the payload (an attached image = scan).

    Returns the decoded JSON body. Raises the last HTTP error (or transport
    error) once every attempt is exhausted, so callers can still decide how to
    degrade.

    Google counts the free quota per model. When the main model's allowance is
    spent (our own budget, a refusal while its breaker is open, or a 429 just
    now) and GEMINI_FALLBACK_MODEL is set, the same request goes to that model
    instead. With no fallback, the error is the main model's, as before.
    """
    kind = kind or _kind(payload)
    models = [settings.gemini_model]
    if settings.gemini_fallback_model and settings.gemini_fallback_model not in models:
        models.append(settings.gemini_fallback_model)
    last: Exception | None = None
    for model in models:
        try:
            return await _generate(model, payload, timeout, kind)
        except Exception as exc:  # noqa: BLE001
            if not gemini_budget.is_quota_error(exc):
                raise
            last = exc
            if model != models[-1]:
                log.warning("gemini quota spent for %s; trying %s", model, models[-1])
    raise last  # type: ignore[misc]


async def _generate(model: str, payload: dict, timeout: float, kind: str) -> dict:
    global _thinking_rejected
    # Our own budget and the breaker after a 429: refuse at once, send nothing.
    gemini_budget.check(kind, model=model)
    url = f"{settings.gemini_base_url}/models/{model}:generateContent"
    last_exc: Exception | None = None
    started = time.monotonic()
    body = _with_thinking(payload, model)
    sent_thinking = body is not payload

    async with httpx.AsyncClient() as client:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = await client.post(
                    url,
                    # In a header, not `?key=`: httpx puts the full URL in its
                    # error messages, so a query-string key ended up in the
                    # logs every time Gemini answered with an error.
                    headers={"x-goog-api-key": settings.gemini_api_key},
                    json=body,
                    timeout=timeout,
                )
            except httpx.TransportError as exc:
                last_exc = exc
                log.warning(
                    "gemini transport error (attempt %d/%d): %s",
                    attempt,
                    MAX_ATTEMPTS,
                    exc,
                )
            else:
                if response.status_code < 400:
                    data = response.json()
                    gemini_budget.record_call(model=model)
                    _log_call(payload, data, attempt, started, kind, model)
                    return data

                log.error(
                    "gemini error %s (attempt %d/%d): %s",
                    response.status_code,
                    attempt,
                    MAX_ATTEMPTS,
                    response.text[:500],
                )
                if response.status_code == 429:
                    # Stop every other call too until Google can answer again.
                    gemini_budget.note_rejected(response.text, model=model)

                # A wrong thinking parameter must not break the feature: drop
                # it for good and repeat this call without it.
                if (
                    response.status_code == 400
                    and sent_thinking
                    and "thinking" in response.text.lower()
                ):
                    log.warning("gemini rejected thinkingConfig; sending without it from now on")
                    _thinking_rejected = True
                    sent_thinking = False
                    body = payload
                    continue

                # A 400/401/403 will fail identically on every retry, so stop
                # immediately instead of burning the user's timeout.
                if response.status_code not in RETRYABLE_STATUSES:
                    response.raise_for_status()

                last_exc = httpx.HTTPStatusError(
                    f"gemini returned {response.status_code}",
                    request=response.request,
                    response=response,
                )

            if attempt < MAX_ATTEMPTS:
                await asyncio.sleep(BACKOFF_BASE_SECONDS * 2 ** (attempt - 1))

    raise last_exc or RuntimeError("gemini request failed")


async def stream_content(payload: dict, timeout: float = 30.0, kind: str | None = None) -> AsyncIterator[dict]:
    """The same request as generate_content, answered piece by piece: yields
    each chunk Gemini streams (a GenerateContentResponse with the next bit of
    text; the last one carries finishReason and usageMetadata).

    Same budget, breaker, thinking setting, key header and fallback model as
    generate_content. Retries (a 503, a dropped connection, a refused thinking
    setting) and the switch to the fallback model happen only before the first
    chunk: once text has been passed on, an error is raised to the caller.
    """
    kind = kind or _kind(payload)
    models = [settings.gemini_model]
    if settings.gemini_fallback_model and settings.gemini_fallback_model not in models:
        models.append(settings.gemini_fallback_model)
    last: Exception | None = None
    for model in models:
        passed_on = False
        try:
            async for chunk in _stream(model, payload, timeout, kind):
                passed_on = True
                yield chunk
            return
        except Exception as exc:  # noqa: BLE001
            if passed_on or not gemini_budget.is_quota_error(exc):
                raise
            last = exc
            if model != models[-1]:
                log.warning("gemini quota spent for %s; trying %s", model, models[-1])
    raise last  # type: ignore[misc]


def _chunk_of(line: str) -> dict | None:
    """One server-sent event line ("data: {...}") as a dict; None for blank
    lines, comments, other fields and anything that is not a JSON object."""
    if not line.startswith("data:"):
        return None
    raw = line[5:].strip()
    if not raw or raw == "[DONE]":
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


async def _stream(model: str, payload: dict, timeout: float, kind: str) -> AsyncIterator[dict]:
    global _thinking_rejected
    gemini_budget.check(kind, model=model)
    # alt=sse asks for server-sent events. The key stays in the header (see _generate).
    url = f"{settings.gemini_base_url}/models/{model}:streamGenerateContent?alt=sse"
    started = time.monotonic()
    body = _with_thinking(payload, model)
    sent_thinking = body is not payload
    last_exc: Exception | None = None
    passed_on = False

    async with httpx.AsyncClient() as client:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                async with client.stream(
                    "POST", url, headers={"x-goog-api-key": settings.gemini_api_key}, json=body, timeout=timeout
                ) as response:
                    if response.status_code < 400:
                        gemini_budget.record_call(model=model)
                        usage: dict = {}
                        async for line in response.aiter_lines():
                            chunk = _chunk_of(line)
                            if chunk is None:
                                continue
                            usage = chunk.get("usageMetadata") or usage
                            passed_on = True
                            yield chunk
                        _log_call(payload, {"usageMetadata": usage}, attempt, started, kind, model)
                        return

                    await response.aread()
                    text = response.text
                    log.error("gemini error %s (attempt %d/%d): %s", response.status_code, attempt, MAX_ATTEMPTS, text[:500])
                    if response.status_code == 429:
                        gemini_budget.note_rejected(text, model=model)
                    if response.status_code == 400 and sent_thinking and "thinking" in text.lower():
                        log.warning("gemini rejected thinkingConfig; sending without it from now on")
                        _thinking_rejected = True
                        sent_thinking = False
                        body = payload
                        continue
                    last_exc = httpx.HTTPStatusError(
                        f"gemini returned {response.status_code}", request=response.request, response=response
                    )
                    if response.status_code not in RETRYABLE_STATUSES:
                        raise last_exc
            except httpx.TransportError as exc:
                if passed_on:
                    # Text was already passed on: asking again would repeat it.
                    raise
                last_exc = exc
                log.warning("gemini transport error (attempt %d/%d): %s", attempt, MAX_ATTEMPTS, exc)

            if attempt < MAX_ATTEMPTS:
                await asyncio.sleep(BACKOFF_BASE_SECONDS * 2 ** (attempt - 1))

    raise last_exc or RuntimeError("gemini request failed")

