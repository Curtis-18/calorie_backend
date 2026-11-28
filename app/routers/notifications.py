import asyncio
import logging
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, distinct, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import async_session_maker, get_db
from app.core.language import get_language
from app.core.rate_limit import push_tests
from app.core.security import get_current_user_id
from app.i18n import t
from app.models.friendship import Friendship
from app.models.notification import DeviceToken, NotificationLog, NotificationPrefs
from app.models.user import Profile
from app.schemas.notifications import DeviceIn, DeviceRemoveIn, PrefsIn, PrefsOut
from app.models.food_log import FoodLog
from app.services.notification_rules import (
    LOG_REMINDER_WINDOW,
    MILESTONE_WINDOW,
    MY_STREAK_WINDOW,
    ANNOUNCEMENTS,
    RECAP_MIN_DAYS,
    Kind,
    decide,
    in_reminder_window,
    in_window,
    local_time,
    milestone_events,
    own_reminders,
    pick_streak_to_save,
    recap_due,
    recap_week,
)
from app.services.progress_service import LogRow, compute_progress
from app.services import announcements, language_pref, progress_read, push_sender
from app.services.notifier import notify, prefs_from_row
from app.services.snap_streaks import streaks_with

log = logging.getLogger("calorie_backend")

router = APIRouter(prefix="/notifications", tags=["notifications"])

LOG_KEEP = timedelta(days=7)


def _utcnow() -> datetime:
    """The scheduler's clock, one place so tests can set it."""
    return datetime.now(timezone.utc)


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
    if data.platform == "web" and push_sender.parse_subscription(data.token) is None:
        raise HTTPException(status_code=422, detail="That isn't a valid browser notification subscription.")
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


@router.post("/devices/remove", status_code=204)
async def remove_device_by_body(
    data: DeviceRemoveIn,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Like DELETE /devices/{token}, for a browser subscription, which is long
    JSON text and does not belong in a URL."""
    await db.execute(delete(DeviceToken).where(DeviceToken.token == data.token, DeviceToken.user_id == user_id))
    await db.commit()
    return None


@router.get("/web-push")
async def web_push_info(user_id: uuid.UUID = Depends(get_current_user_id)):
    """Whether browsers can be notified, and the public key a browser needs to
    subscribe. The key is not a secret; the app asks here so it needs no
    rebuild when the keys are set or changed."""
    ready = push_sender.web_push_ready()
    return {"enabled": ready, "public_key": settings.vapid_public_key if ready else None}


TEST_TITLE = "Notifications are on 🔔"
TEST_BODY = "This is a test. You'll get friends' bites and gentle reminders here, never more than a few a day."


@router.post("/test")
async def send_test(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
    lang: str = Depends(get_language),
):
    """Send yourself one notification now, to check this device is set up.
    Skips quiet hours and the daily cap (you asked for it) and is not logged."""
    push_tests.check("push_test", user_id, "That's enough tests for now. Try again in a while.")
    tokens = list((await db.execute(select(DeviceToken.token).where(DeviceToken.user_id == user_id))).scalars().all())
    if not tokens:
        return {"status": "no_device"}
    try:
        status = await push_sender.send(tokens, t(lang, TEST_TITLE), t(lang, TEST_BODY), {"kind": "test"})
    except Exception:  # noqa: BLE001
        log.exception("test push failed")
        status = "failed"
    return {"status": status}


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


async def _send_milestone(db: AsyncSession, uid: uuid.UUID, prefs, local: datetime, now: datetime) -> str | None:
    """At most one piece of good news (a freeze that covered yesterday, a new
    badge, a new level), or None when there is nothing to tell. Each event has
    its own dedupe key, so the next hourly run moves on to the next one."""
    # Only load the person's history when something could actually be sent.
    allowed = {k for k in (Kind.STREAK_FREEZE, Kind.MILESTONE) if decide(k, prefs, now, 0).allowed}
    if not allowed:
        return None
    today = local.date()
    lang = await language_pref.recall(db, uid)
    inputs = await progress_read.load_inputs(db, uid, today)
    events = milestone_events(
        progress_read.progress_on(inputs, today, lang),
        progress_read.progress_on(inputs, today - timedelta(days=1), lang),
        today,
    )
    for kind, key, values in events:
        if kind not in allowed:
            continue
        status = await notify(db, uid, kind, dedupe_key=key, now=now, **values)
        if status != "duplicate":
            return status  # sent, or the rules said no for now: either way, one a run
    return None


async def _send_recap(db: AsyncSession, uid: uuid.UUID, prefs, local: datetime, now: datetime) -> str | None:
    """Sunday evening: how many days the person logged this week (Monday to
    today, their own days), only when it is 2 or more. None when nothing was
    tried. The week's dedupe key keeps it to one a week."""
    if not decide(Kind.WEEKLY_RECAP, prefs, now, 0).allowed:
        return None  # switched off, paused or quiet hours: don't even count
    today = local.date()
    monday, key, line = recap_week(today)
    days = (
        await db.execute(
            select(func.count(distinct(FoodLog.log_date))).where(
                FoodLog.user_id == uid, FoodLog.log_date >= monday, FoodLog.log_date <= today
            )
        )
    ).scalar_one_or_none() or 0
    if days < RECAP_MIN_DAYS:
        return None
    return await notify(db, uid, Kind.WEEKLY_RECAP, dedupe_key=key, now=now, count=int(days), variant=line)


# One run at a time in this process (a slow run and the next call must not
# overlap; the dedupe keys would still stop double sends, but not double work).
_job_lock = asyncio.Lock()

# What the last finished run did, for tests and the log line.
last_run: dict = {}

# The UTC hour ("2026-11-28T14") whose work this process has finished. The
# scheduler may call every 10 minutes (that also keeps Render's free server
# awake, so the call doesn't time out while it wakes); the per-person work
# still runs once an hour. Lost on a restart, which only means one extra run:
# the dedupe keys stop anything being sent twice.
_hour_done: str | None = None


def _check_cron_secret(x_cron_secret: str | None) -> None:
    if not settings.cron_secret:
        raise HTTPException(404, "Not found")
    # Bytes: compare_digest raises on a non-ASCII str, which was a 500.
    if not x_cron_secret or not secrets.compare_digest(x_cron_secret.encode(), settings.cron_secret.encode()):
        raise HTTPException(403, "Forbidden")


@router.post("/cron/streak-reminders", status_code=202)
@router.get("/cron/streak-reminders", status_code=202, operation_id="streak_reminders_get")
async def streak_reminders(background: BackgroundTasks, x_cron_secret: str | None = Header(default=None)):
    """For a scheduler (cron-job.org): every 10 minutes is best (it keeps the
    server awake), hourly at least. Answers at once with 202 and does the work
    straight after, in the background, at most once per hour.

    Why at once: cron-job.org gives up after 30 seconds ("Failed (timeout)")
    and switches a job off after about 25 failures in a row. Render's free
    server takes 30-60 s just to wake up, and the work itself grows with every
    person who has notifications on, so answering only after the work made the
    job fail (owner, 28 Nov 2026: "the cronjob.org thing we set up failed").
    GET as well as POST because GET is cron-job.org's default method.

    The work (see _send_reminders) sends what is due for each person at their
    own local time, each at most once a day, always through the daily cap,
    quiet hours and switches. Then it deletes bites and stories older than
    24 hours (_purge_expired_photos).
    Disabled until CRON_SECRET is set. The path keeps its old name so an
    existing schedule keeps working.
    """
    _check_cron_secret(x_cron_secret)
    if _job_lock.locked():
        return {"status": "already_running"}
    background.add_task(_run_job, _utcnow())
    return {"status": "started"}


async def _run_job(now: datetime) -> None:
    """The background part. Never raises: nobody is waiting for the answer,
    so a failure can only be seen in the Render log ("cron job failed")."""
    global _hour_done
    if _job_lock.locked():
        return
    async with _job_lock:
        hour = now.strftime("%Y-%m-%dT%H")
        if hour == _hour_done:
            return  # this hour's work is done; this call only kept the server awake
        started = time.monotonic()
        try:
            async with async_session_maker() as db:
                results = await _send_reminders(db, now)
        except Exception:  # noqa: BLE001
            log.exception("cron job failed")
            return
        _hour_done = hour
        results["purged"] = await _purge_expired_photos()
        last_run.clear()
        last_run.update(results)
        log.info(
            "cron job done checked=%s sent=%s purged=%s secs=%.1f",
            results["checked"], results["sent"], results["purged"], time.monotonic() - started,
        )


async def _purge_expired_photos() -> int:
    """Delete bites and stories past their 24 hours (photos and rows). The
    privacy page promises that, and until 28 Nov it only happened when someone
    opened their inbox or the stories feed, or if a separate /snaps/purge job
    existed (nobody knew whether one did). Never raises; 0 when storage isn't
    set up (no SUPABASE_SERVICE_ROLE_KEY), so the log isn't filled with errors."""
    from app.routers.snaps import purge_expired
    from app.routers.stories import purge_expired_stories
    from app.services import storage_service

    if not storage_service.configured():
        return 0
    return await purge_expired(limit=500) + await purge_expired_stories(limit=500)


async def _send_reminders(db: AsyncSession, now: datetime) -> dict:
    """Everything due right now, for everyone with a registered device:

    - afternoon: "you haven't logged anything today"
    - evening: "your logging streak ends tonight" (only with a running streak)
    - evening: "your streak with a friend ends tonight" (a bite is owed)
    - daytime: a freeze covered yesterday, a new badge or a new level (one a run)
    - Sunday 17:00-19:00: how many days you logged this week (2 or more only)
    """
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
        wants_milestone = in_window(local.hour, MILESTONE_WINDOW)
        wants_recap = recap_due(local)
        if not (wants_pair or wants_own or wants_milestone or wants_recap):
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
                # A failed statement leaves the transaction aborted: without
                # this, everyone after them failed as well.
                await db.rollback()

        # The week's recap before badges: it has only two hours on one day, while
        # badge news has all day; when a recap went out, badge news waits an hour.
        recap_went = False
        if wants_recap:
            try:
                status = await _send_recap(db, uid, prefs, local, now)
                if status is not None:
                    counted(status)
                    recap_went = status in ("sent", "dry_run")
            except Exception:  # noqa: BLE001 - one person's failure must not stop the rest
                log.exception("weekly recap failed for a user")
                await db.rollback()

        # Before the friend streaks: that block ends early with `continue`.
        if wants_milestone and not recap_went:
            try:
                status = await _send_milestone(db, uid, prefs, local, now)
                if status is not None:
                    counted(status)
            except Exception:  # noqa: BLE001 - one person's failure must not stop the rest
                log.exception("milestone notification failed for a user")
                await db.rollback()

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
                await db.rollback()

    await db.execute(delete(NotificationLog).where(NotificationLog.created_at < now - LOG_KEEP))
    await db.commit()
    return results


class AnnounceIn(BaseModel):
    release: str = Field(max_length=100)
    # False (the default) only counts who would be told; nothing is sent.
    send: bool = False
    # Real deliveries per call; call again to carry on (nobody is sent it twice).
    limit: int = Field(default=100, ge=1, le=500)


@router.post("/cron/announce")
async def announce(
    data: AnnounceIn,
    x_cron_secret: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Tell everyone with a registered device about a release, once. Run by hand.

    Without `"send": true` it only previews: how many people would get it and
    why the others would not (quiet hours, paused, already told). Sending needs
    real web push to be switched on, otherwise a "dry run" would be recorded as
    delivered and the real send afterwards would skip everyone.

    Disabled until CRON_SECRET is set, like the reminders.
    """
    if not settings.cron_secret:
        raise HTTPException(404, "Not found")
    if not x_cron_secret or not secrets.compare_digest(x_cron_secret.encode(), settings.cron_secret.encode()):
        raise HTTPException(403, "Forbidden")
    if data.release not in ANNOUNCEMENTS:
        raise HTTPException(404, "No announcement with that id")
    if data.send and not push_sender.web_push_ready():
        raise HTTPException(409, "Web push is not switched on (PUSH_MODE=web with the VAPID keys), so nothing was sent.")
    return await announcements.broadcast(db, data.release, send=data.send, limit=data.limit)
