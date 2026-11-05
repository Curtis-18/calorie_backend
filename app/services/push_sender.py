"""Delivering a push to a phone.

Only the dry-run provider exists until the Apple Developer account and the
Firebase credentials do. It records nothing itself (the notifier writes the
log row); it just reports what it would have done, so the whole pipeline,
caps and quiet hours included, runs and is testable today. Turning on real
delivery later means adding a provider here and setting PUSH_MODE.
"""

import logging

from app.core.config import settings

log = logging.getLogger("calorie_backend")


class PushUnavailable(Exception):
    """The configured provider could not deliver."""


async def send(tokens: list[str], title: str, body: str, data: dict[str, str] | None = None) -> str:
    """Send to [tokens]. Returns the status to record: "sent" or "dry_run"."""
    mode = settings.push_mode
    if mode == "dry_run":
        log.info("push (dry run) to %d device(s): %s | %s", len(tokens), title, body)
        return "dry_run"
    raise PushUnavailable(f"push mode {mode!r} has no provider yet")
