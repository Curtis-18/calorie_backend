"""Telling everyone about something new, once.

Used by hand (never by a schedule) through `POST /notifications/cron/announce`.
Each person is judged by the same rules as any other notification (paused,
quiet hours, the daily cap), so nobody is woken at night; the announcement's own
dedupe key means running it again only reaches the people it missed (they were
asleep, or a delivery failed) and never sends the same one twice.
"""

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import DeviceToken, NotificationLog
from app.services import notifier
from app.services.notification_rules import ANNOUNCEMENTS, Kind

log = logging.getLogger("calorie_backend")

# Results that cost a real push (or tried to), so a batch limit can stop at them.
_DELIVERIES = ("sent", "failed", "dry_run", "no_device")


def dedupe_key(release: str) -> str:
    return f"announce:{release}"


async def broadcast(
    db: AsyncSession,
    release: str,
    *,
    send: bool,
    limit: int = 100,
    now: datetime | None = None,
) -> dict:
    """Preview (default) or send the announcement for [release] to everyone who
    has a registered device. Stops after [limit] deliveries and says so with
    `more`; run it again to carry on.

    Returns {"mode", "people", "counts": {result: n}, "more"}.
    """
    if release not in ANNOUNCEMENTS:
        raise KeyError(release)
    now = now or datetime.now(timezone.utc)
    key = dedupe_key(release)
    people: list[uuid.UUID] = list(
        (await db.execute(select(DeviceToken.user_id).distinct().order_by(DeviceToken.user_id))).scalars().all()
    )
    counts: dict[str, int] = {}
    delivered = 0
    more = False

    def add(result: str) -> None:
        counts[result] = counts.get(result, 0) + 1

    for uid in people:
        if send and delivered >= limit:
            more = True
            break
        try:
            if send:
                result = await notifier.notify(db, uid, Kind.ANNOUNCEMENT, dedupe_key=key, release=release, now=now)
                if result == "failed":
                    # Free the claim so the next run tries this person again.
                    await db.execute(
                        delete(NotificationLog).where(
                            NotificationLog.user_id == uid,
                            NotificationLog.dedupe_key == key,
                            NotificationLog.status == "failed",
                        )
                    )
                    await db.commit()
                if result in _DELIVERIES:
                    delivered += 1
            else:
                result = await notifier.preview(db, uid, Kind.ANNOUNCEMENT, dedupe_key=key, now=now)
        except Exception:  # noqa: BLE001 - one person's problem must not stop the rest
            log.exception("announcement failed for a user")
            await db.rollback()
            result = "error"
        add(result)

    return {"mode": "send" if send else "preview", "people": len(people), "counts": counts, "more": more}
