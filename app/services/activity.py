"""The in-app Notifications list: bites and reactions from friends.

Writing never breaks the thing that caused it (it runs in the background and
swallows errors), and reading treats a missing table (migration not run yet)
as an empty list.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, delete, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_maker
from app.models.activity import Activity
from app.models.friendship import Block
from app.models.user import Profile

log = logging.getLogger("calorie_backend")

KINDS = ("bite", "reaction")
KEEP = timedelta(days=30)
PAGE = 40


def bite_id(kind: str, dedupe_key: str | None) -> uuid.UUID | None:
    """The bite a "bite" line is about, so the app can open that exact bite.
    Read from the dedupe key `snap:<id>` that snaps.py has always written, so
    no new column is needed. Anything else (a reaction, an odd key) is None."""
    if kind != "bite" or not dedupe_key or not dedupe_key.startswith("snap:"):
        return None
    try:
        return uuid.UUID(dedupe_key[5:])
    except ValueError:
        return None


async def record(user_id: uuid.UUID, kind: str, actor_id: uuid.UUID, *, emoji: str | None = None, dedupe_key: str | None = None) -> bool:
    """Add a line for [user_id]. Own session, never raises; False if nothing was added."""
    if kind not in KINDS or user_id == actor_id:
        return False
    try:
        async with async_session_maker() as db:
            row = {"id": uuid.uuid4(), "user_id": user_id, "actor_id": actor_id, "kind": kind, "emoji": emoji, "dedupe_key": dedupe_key}
            added = await db.execute(pg_insert(Activity).values(row).on_conflict_do_nothing().returning(Activity.id))
            made = added.scalar_one_or_none() is not None
            await db.commit()
            return made
    except Exception:  # noqa: BLE001 - a notification list must never break a bite or a reaction
        log.warning("could not record activity", exc_info=True)
        return False


def _visible(user_id: uuid.UUID, since: datetime):
    """Recent lines, and nothing from someone blocked either way."""
    blocked = exists().where(
        or_(
            and_(Block.blocker_id == user_id, Block.blocked_id == Activity.actor_id),
            and_(Block.blocker_id == Activity.actor_id, Block.blocked_id == user_id),
        )
    )
    return (Activity.user_id == user_id, Activity.created_at >= since, ~blocked)


async def feed(db: AsyncSession, user_id: uuid.UUID, *, now: datetime | None = None) -> dict:
    """The latest lines (newest first) and how many are unseen. Own savepoint,
    never raises: an empty list when the table is missing."""
    since = (now or datetime.now(timezone.utc)) - KEEP
    try:
        async with db.begin_nested():
            rows = (
                await db.execute(
                    select(
                        Activity.id, Activity.kind, Activity.emoji, Activity.created_at, Activity.seen_at, Activity.dedupe_key,
                        Profile.username,
                    )
                    .join(Profile, Profile.id == Activity.actor_id)
                    .where(*_visible(user_id, since))
                    .order_by(Activity.created_at.desc())
                    .limit(PAGE)
                )
            ).all()
            unread = (
                await db.execute(select(func.count()).select_from(Activity).where(*_visible(user_id, since), Activity.seen_at.is_(None)))
            ).scalar_one_or_none()
    except Exception:  # noqa: BLE001
        log.warning("activity: could not read the list", exc_info=True)
        return {"items": [], "unread": 0}
    try:
        unread = max(0, int(unread or 0))
    except (TypeError, ValueError):
        unread = 0
    return {
        "items": [
            {
                "id": r.id, "kind": r.kind, "username": r.username or "", "emoji": r.emoji, "created_at": r.created_at,
                "seen": r.seen_at is not None, "snap_id": bite_id(r.kind, getattr(r, "dedupe_key", None)),
            }
            for r in rows
        ],
        "unread": unread,
    }


async def mark_seen(db: AsyncSession, user_id: uuid.UUID, *, now: datetime | None = None) -> None:
    """Everything is read now. Also drops lines older than [KEEP]. Never raises."""
    now = now or datetime.now(timezone.utc)
    try:
        async with db.begin_nested():
            await db.execute(update(Activity).where(Activity.user_id == user_id, Activity.seen_at.is_(None)).values(seen_at=now))
            await db.execute(delete(Activity).where(Activity.user_id == user_id, Activity.created_at < now - KEEP))
        await db.commit()
    except Exception:  # noqa: BLE001
        log.warning("activity: could not mark as seen", exc_info=True)
        await db.rollback()
