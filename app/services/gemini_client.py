import asyncio
import copy
import logging
import time

import httpx

from app.core.config import settings

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


def _with_thinking(payload: dict) -> dict:
    """A copy of [payload] asking for minimal thinking, unless the caller set
    its own or Gemini already rejected the parameter."""
    config = thinking_config(settings.gemini_model)
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


def _log_call(payload: dict, data: dict, attempts: int, started: float, kind: str | None = None) -> None:
    usage = data.get("usageMetadata") or {}
    log.info(
        "gemini_call kind=%s model=%s attempts=%d ms=%d prompt_tokens=%s output_tokens=%s thought_tokens=%s",
        kind or _kind(payload),
        settings.gemini_model,
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
    """
    global _thinking_rejected
    url = f"{settings.gemini_base_url}/models/{settings.gemini_model}:generateContent"
    last_exc: Exception | None = None
    started = time.monotonic()
    body = _with_thinking(payload)
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
                    _log_call(payload, data, attempt, started, kind)
                    return data

                log.error(
                    "gemini error %s (attempt %d/%d): %s",
                    response.status_code,
                    attempt,
                    MAX_ATTEMPTS,
                    response.text[:500],
                )
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
