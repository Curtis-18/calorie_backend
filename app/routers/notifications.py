import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user_id
from app.models.friendship import Friendship
from app.models.notification import DeviceToken, NotificationLog, NotificationPrefs
from app.models.user import Profile
from app.schemas.notifications import DeviceIn, PrefsIn, PrefsOut
from app.models.food_log import FoodLog
from app.services.notification_rules import (
    LOG_REMINDER_WINDOW,
    MY_STREAK_WINDOW,
    Kind,
    in_reminder_window,
    in_window,
    local_time,
    own_reminders,
    pick_streak_to_save,
)
from app.services.progress_service import LogRow, compute_progress
from app.services.notifier import notify, prefs_from_row
from app.services.snap_streaks import streaks_with

log = logging.getLogger("calorie_backend")

router = APIRouter(prefix="/notifications", tags=["notifications"])

LOG_KEEP = timedelta(days=7)


def _out(row: NotificationPrefs | None) -> dict:
    p = prefs_from_row(row)
    return {
        "friend_snaps": p.friend_snaps,
        "reactions": p.reactions,
        "streak_reminders": p.streak_reminders,
        "milestones": p.milestones,
        "meal_nudge_hour": p.meal_nudge_hour,
        "quiet_start": p.quiet_start,
        "quiet_end": p.quiet_end,
        "utc_offset_minutes": p.utc_offset_minutes,
        "paused_until": p.paused_until,
        "daily_cap": settings.push_daily_cap,
    }


@router.get("/prefs", response_model=PrefsOut)
async def get_prefs(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    row = (await db.execute(select(NotificationPrefs).where(NotificationPrefs.user_id == user_id))).scalar_one_or_none()
    return _out(row)


@router.post("/prefs", response_model=PrefsOut)
async def update_prefs(
    data: PrefsIn,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Change any of your notification choices. POST rather than PATCH so the
    CORS method list stays as it is."""
    values = data.model_dump(exclude_unset=True, exclude={"pause_days", "meal_nudge_hour"})
    values = {k: v for k, v in values.items() if v is not None}
    if "meal_nudge_hour" in data.model_fields_set and data.meal_nudge_hour is not None:
        values["meal_nudge_hour"] = None if data.meal_nudge_hour < 0 else data.meal_nudge_hour
    if data.pause_days is not None:
        values["paused_until"] = (
            datetime.now(timezone.utc) + timedelta(days=data.pause_days) if data.pause_days > 0 else None
        )
    values["updated_at"] = datetime.now(timezone.utc)

    await db.execute(
        pg_insert(NotificationPrefs)
        .values(user_id=user_id, **values)
        .on_conflict_do_update(index_elements=[NotificationPrefs.user_id], set_=values)
    )
    await db.commit()
    row = (await db.execute(select(NotificationPrefs).where(NotificationPrefs.user_id == user_id))).scalar_one_or_none()
    return _out(row)


@router.post("/devices", status_code=204)
async def register_device(
    data: DeviceIn,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Remember this phone's push token. A token that was on another account
    moves to this one, so signing out and in as someone else can't leave the
    old person getting the new person's notifications."""
    now = datetime.now(timezone.utc)
    stmt = pg_insert(DeviceToken).values(token=data.token, user_id=user_id, platform=data.platform, last_seen=now)
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=[DeviceToken.token],
            set_={"user_id": user_id, "platform": data.platform, "last_seen": now},
        )
    )
    if data.utc_offset_minutes is not None:
        await db.execute(
            pg_insert(NotificationPrefs)
            .values(user_id=user_id, utc_offset_minutes=data.utc_offset_minutes)
            .on_conflict_do_update(
                index_elements=[NotificationPrefs.user_id],
                set_={"utc_offset_minutes": data.utc_offset_minutes},
            )
        )
    await db.commit()
    return None


@router.delete("/devices/{token}", status_code=204)
async def remove_device(
    token: str,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Forget this phone (on sign-out). Only removes your own token."""
    await db.execute(delete(DeviceToken).where(DeviceToken.token == token, DeviceToken.user_id == user_id))
    await db.commit()
    return None


async def _logging_state(db: AsyncSession, uid: uuid.UUID, today) -> tuple[int, bool]:
    """(current logging streak, logged something today) using the same maths
    as the Progress screen, so a reminder never disagrees with the app."""
    result = await db.execute(
        select(
            FoodLog.log_date, FoodLog.meal_type, FoodLog.source, FoodLog.calories, FoodLog.protein_g, FoodLog.timestamp
        ).where(FoodLog.user_id == uid, FoodLog.log_date <= today)
    )
    progress = compute_progress([LogRow(*row) for row in result.all()], today=today, calorie_target=None, protein_target=None)
    return progress["streak"]["current"], progress["streak"]["logged_today"]


@router.post("/cron/streak-reminders")
async def streak_reminders(
    x_cron_secret: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """For a scheduler, run hourly. Sends the reminders that are due for each
    person at their own local time, each at most once a day (the day's dedupe
    key) and always through the daily cap, quiet hours and switches:

    - afternoon: "you haven't logged anything today"
    - evening: "your logging streak ends tonight" (only with a running streak)
    - evening: "your streak with a friend ends tonight" (a bite is owed)

    Disabled until CRON_SECRET is set. The path keeps its old name so an
    existing schedule keeps working.
    """
    if not settings.cron_secret:
        raise HTTPException(404, "Not found")
    if not x_cron_secret or not secrets.compare_digest(x_cron_secret, settings.cron_secret):
        raise HTTPException(403, "Forbidden")

    now = datetime.now(timezone.utc)
    user_ids = (await db.execute(select(DeviceToken.user_id).distinct())).scalars().all()
    pref_rows = {
        r.user_id: r
        for r in (
            await db.execute(select(NotificationPrefs).where(NotificationPrefs.user_id.in_(user_ids)))
        ).scalars().all()
    } if user_ids else {}

    results = {"checked": 0, "sent": 0}

    def counted(status: str) -> None:
        if status in ("sent", "dry_run"):
            results["sent"] += 1

    for uid in user_ids:
        prefs = prefs_from_row(pref_rows.get(uid))
        local = local_time(now, prefs)
        day = local.date().isoformat()
        wants_pair = in_reminder_window(local.hour)
        wants_own = in_window(local.hour, LOG_REMINDER_WINDOW) or in_window(local.hour, MY_STREAK_WINDOW)
        if not (wants_pair or wants_own):
            continue
        results["checked"] += 1

        # Your own logging first: it is the more important reminder.
        if wants_own:
            try:
                streak, logged_today = await _logging_state(db, uid, local.date())
                for kind, prefix in own_reminders(local.hour, logged_today=logged_today, streak=streak):
                    counted(await notify(db, uid, kind, dedupe_key=f"{prefix}:{day}", count=streak, now=now))
            except Exception:  # noqa: BLE001 - one person's failure must not stop the rest
                log.exception("logging reminder failed for a user")

        if wants_pair:
            try:
                pairs = (
                    await db.execute(
                        select(Friendship.requester_id, Friendship.addressee_id).where(
                            Friendship.status == "accepted",
                            (Friendship.requester_id == uid) | (Friendship.addressee_id == uid),
                        )
                    )
                ).all()
                friend_ids = [b if a == uid else a for a, b in pairs]
                if not friend_ids:
                    continue
                streaks = await streaks_with(db, uid, friend_ids, local.date())
                names = {
                    i: n
                    for i, n in (
                        await db.execute(select(Profile.id, Profile.username).where(Profile.id.in_(friend_ids)))
                    ).all()
                    if n
                }
                pick = pick_streak_to_save(
                    [(names[f], s.count, s.sent_today) for f, s in streaks.items() if f in names]
                )
                if pick is None:
                    continue
                name, count = pick
                counted(
                    await notify(db, uid, Kind.STREAK_AT_RISK, dedupe_key=f"streak:{day}", name=name, count=count, now=now)
                )
            except Exception:  # noqa: BLE001
                log.exception("streak reminder failed for a user")

    await db.execute(delete(NotificationLog).where(NotificationLog.created_at < now - LOG_KEEP))
    await db.commit()
    return results
