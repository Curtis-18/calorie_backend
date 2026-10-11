import asyncio
import logging

import httpx

from app.core.config import settings

log = logging.getLogger("calorie_backend")

# Gemini answers these under load, and they are transient rather than a real
# failure: "This model is currently experiencing high demand. Spikes in demand
# are usually temporary." Previously a single 503 became an httpx
# HTTPStatusError and every caller surfaced it as an opaque 500 to the user.
# A short retry rides out the spike; only a run of them means the service is
# genuinely down.
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 0.5


async def generate_content(payload: dict, timeout: float = 30.0) -> dict:
    """POST to Gemini, retrying transient failures with exponential backoff.

    Returns the decoded JSON body. Raises the last HTTP error (or transport
    error) once every attempt is exhausted, so callers can still decide how to
    degrade.
    """
    url = f"{settings.gemini_base_url}/models/{settings.gemini_model}:generateContent"
    last_exc: Exception | None = None

    async with httpx.AsyncClient() as client:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = await client.post(
                    url,
                    params={"key": settings.gemini_api_key},
                    json=payload,
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
                    return response.json()

                log.error(
                    "gemini error %s (attempt %d/%d): %s",
                    response.status_code,
                    attempt,
                    MAX_ATTEMPTS,
                    response.text[:500],
                )
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
