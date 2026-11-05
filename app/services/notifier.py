"""Sends a notification to a person, if the rules allow it.

Every call goes through `notify`, so the daily cap, quiet hours, pause and
per-kind switches can't be skipped by a new caller. Notifications are never
allowed to break the action that caused them: `notify_user` swallows and logs
every error, and it runs in the background after the response.
"""

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import async_session_maker
from app.models.notification import DeviceToken, NotificationLog, NotificationPrefs
from app.services import push_sender
from app.services.notification_rules import Kind, Prefs, copy_for, decide, local_day_bounds_utc

log = logging.getLogger("calorie_backend")

COUNTED = ("sent", "dry_run")


def prefs_from_row(row: NotificationPrefs | None) -> Prefs:
    if row is None:
        return Prefs()
    return Prefs(
        friend_snaps=row.friend_snaps,
        reactions=row.reactions,
        streak_reminders=row.streak_reminders,
        milestones=row.milestones,
        meal_nudge_hour=row.meal_nudge_hour,
        quiet_start=row.quiet_start,
        quiet_end=row.quiet_end,
        utc_offset_minutes=row.utc_offset_minutes,
        paused_until=row.paused_until,
    )


async def notify(
    db: AsyncSession,
    user_id: uuid.UUID,
    kind: Kind,
    *,
    dedupe_key: str | None = None,
    now: datetime | None = None,
    **ctx,
) -> str:
    """Returns what happened: "sent", "dry_run", "no_device", "duplicate", "failed",
    or the reason the rules said no ("switched_off", "paused", "quiet_hours", "daily_cap")."""
    now = now or datetime.now(timezone.utc)

    tokens = (await db.execute(select(DeviceToken.token).where(DeviceToken.user_id == user_id))).scalars().all()
    if not tokens:
        return "no_device"

    prefs = prefs_from_row(
        (await db.execute(select(NotificationPrefs).where(NotificationPrefs.user_id == user_id))).scalar_one_or_none()
    )

    start, end = local_day_bounds_utc(now, prefs)
    sent_today = (
        await db.execute(
            select(func.count())
            .select_from(NotificationLog)
            .where(
                NotificationLog.user_id == user_id,
                NotificationLog.status.in_(COUNTED),
                NotificationLog.created_at >= start,
                NotificationLog.created_at < end,
            )
        )
    ).scalar_one()

    decision = decide(kind, prefs, now, sent_today, cap=settings.push_daily_cap)
    if not decision.allowed:
        return decision.reason

    title, body = copy_for(kind, dedupe_key or str(uuid.uuid4()), **ctx)

    # Claim the dedupe key first: if it is already taken (the scheduler ran
    # twice, or the app retried), do nothing. The unique index decides.
    row = {
        "id": uuid.uuid4(), "user_id": user_id, "kind": kind.value, "title": title, "body": body,
        "status": "pending", "dedupe_key": dedupe_key, "created_at": now,
    }
    inserted = await db.execute(
        pg_insert(NotificationLog).values(row).on_conflict_do_nothing().returning(NotificationLog.id)
    )
    if inserted.scalar_one_or_none() is None:
        return "duplicate"

    try:
        status = await push_sender.send(list(tokens), title, body, {"kind": kind.value})
    except Exception:  # noqa: BLE001 - delivery problems are logged, never raised
        log.exception("push delivery failed")
        status = "failed"
    await db.execute(
        NotificationLog.__table__.update().where(NotificationLog.id == row["id"]).values(status=status)
    )
    await db.commit()
    return status


async def notify_user(user_id: uuid.UUID, kind: Kind, *, dedupe_key: str | None = None, **ctx) -> str:
    """`notify` in its own session, for background tasks. Never raises."""
    try:
        async with async_session_maker() as db:
            return await notify(db, user_id, kind, dedupe_key=dedupe_key, **ctx)
    except Exception:  # noqa: BLE001
        log.exception("notification failed")
        return "failed"
