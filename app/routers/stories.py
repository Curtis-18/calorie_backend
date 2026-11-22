"""Stories: a food photo all of your friends can see for 24 hours.

A story is a broadcast, so it deliberately does not count toward pair streaks:
those need the two of you to send each other a bite. Like bites, a story is a
photo and a caption only, never calorie numbers.
"""

import logging
import uuid
from datetime import date as date_type, datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import async_session_maker, get_db
from app.core.dates import resolve_today
from app.core.security import get_current_user_id
from app.models.friendship import Friendship
from app.models.story import ContentReport, Story, StoryView
from app.models.user import Profile
from app.schemas.snaps import REACTIONS, ReactIn, ReportIn
from app.schemas.stories import StoryFeedOut, StoryIn, StoryPostedOut
from app.services import avatars, storage_service
from app.services.images import decode_photo
from app.services.notification_rules import Kind
from app.services.activity import record as record_activity
from app.services.notifier import notify_user
from app.services.snap_streaks import streaks_with
from app.services.storage_service import StorageUnavailable

log = logging.getLogger("calorie_backend")

router = APIRouter(prefix="/stories", tags=["stories"])

STORY_LIFETIME = timedelta(hours=24)
# Live stories one person can have at once. Generous for real use, and stops
# someone flooding every friend's screen.
MAX_LIVE_STORIES = 20
NOT_SET_UP = "Stories aren't available right now. Please try again later."
GONE = "That story has disappeared."


def _require_storage() -> None:
    if not storage_service.configured():
        raise HTTPException(503, NOT_SET_UP)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _friend_ids(db: AsyncSession, me: uuid.UUID) -> set[uuid.UUID]:
    rows = (
        await db.execute(
            select(Friendship.requester_id, Friendship.addressee_id).where(
                Friendship.status == "accepted",
                or_(Friendship.requester_id == me, Friendship.addressee_id == me),
            )
        )
    ).all()
    return {b if a == me else a for a, b in rows}


async def _usernames(db: AsyncSession, ids) -> dict[uuid.UUID, str]:
    ids = list(ids)
    if not ids:
        return {}
    rows = (await db.execute(select(Profile.id, Profile.username).where(Profile.id.in_(ids)))).all()
    return {i: n for i, n in rows if n}


async def _sign(paths: list[str]) -> dict[str, str | None]:
    try:
        return await storage_service.sign(paths)
    except StorageUnavailable:
        log.exception("could not sign story links")
        return {p: None for p in paths}


async def purge_expired_stories(limit: int = 100) -> int:
    """Delete expired stories: the photo from storage, then the rows."""
    try:
        async with async_session_maker() as db:
            rows = (
                await db.execute(select(Story.id, Story.storage_path).where(Story.expires_at <= _now()).limit(limit))
            ).all()
            if not rows:
                return 0
            await storage_service.delete([p for _, p in rows])
            await db.execute(delete(Story).where(Story.id.in_([i for i, _ in rows])))
            await db.commit()
            return len(rows)
    except Exception:  # noqa: BLE001 - housekeeping must never break a request
        log.exception("purging expired stories failed")
        return 0


@router.post("", response_model=StoryPostedOut)
async def post_story(
    data: StoryIn,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Add a food photo to your story. Repeating the same request (same id)
    is harmless: it returns the original result."""
    _require_storage()
    try:
        existing = (await db.execute(select(Story).where(Story.id == data.id))).scalar_one_or_none()
    except Exception:  # noqa: BLE001 - the table isn't there until the migration is run
        await db.rollback()
        log.exception("could not read stories")
        raise HTTPException(503, NOT_SET_UP)
    if existing is not None:
        if existing.user_id != user_id:
            raise HTTPException(409, "That story id is already used.")
        return {"story_id": existing.id, "expires_at": existing.expires_at}

    image, mime, ext = decode_photo(data.image, settings.max_snap_bytes)

    live = (
        await db.execute(
            select(func.count()).select_from(Story).where(Story.user_id == user_id, Story.expires_at > _now())
        )
    ).scalar_one()
    if live >= MAX_LIVE_STORIES:
        raise HTTPException(429, "Your story is full for now. You can add more as today's photos disappear.")

    path = f"{user_id}/story-{data.id}.{ext}"
    try:
        await storage_service.upload(path, image, mime)
    except StorageUnavailable:
        log.exception("story upload failed")
        raise HTTPException(502, "Couldn't upload that photo. Please try again.")

    expires = _now() + STORY_LIFETIME
    try:
        db.add(Story(
            id=data.id, user_id=user_id, storage_path=path,
            caption=(data.caption or "").strip() or None, expires_at=expires,
        ))
        await db.commit()
    except Exception:  # noqa: BLE001
        await db.rollback()
        log.exception("saving story failed")
        try:
            await storage_service.delete([path])
        except StorageUnavailable:
            pass
        raise HTTPException(500, "Couldn't add that to your story. Please try again.")
    return {"story_id": data.id, "expires_at": expires}


@router.get("", response_model=StoryFeedOut)
async def feed(
    background: BackgroundTasks,
    date: date_type | None = None,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Your own live stories (with who has seen them) and your friends'.
    Friends with something you haven't seen come first, then the people you
    have the longest streaks with."""
    _require_storage()
    # Only current friends: unfriending or blocking hides their stories.
    friends = await _friend_ids(db, user_id)
    try:
        stories = (
            await db.execute(
                select(Story)
                .where(Story.user_id.in_([user_id, *friends]), Story.expires_at > _now())
                .order_by(Story.created_at.asc())
            )
        ).scalars().all()
    except Exception:  # noqa: BLE001 - the table isn't there until the migration is run
        await db.rollback()
        log.exception("could not read stories")
        raise HTTPException(503, NOT_SET_UP)
    if not stories:
        return {"mine": [], "friends": []}

    my_story_ids = [s.id for s in stories if s.user_id == user_id]
    views = (
        await db.execute(
            select(StoryView).where(
                StoryView.story_id.in_([s.id for s in stories]),
                # My own views of friends' stories, and everyone's views of mine.
                or_(StoryView.viewer_id == user_id, StoryView.story_id.in_(my_story_ids)),
            )
        )
    ).scalars().all()
    my_views = {v.story_id: v for v in views if v.viewer_id == user_id}
    # Someone who has since been removed or blocked no longer shows as a viewer.
    seen_mine = [v for v in views if v.viewer_id != user_id and v.viewer_id in friends]

    owners = {s.user_id for s in stories if s.user_id != user_id}
    people = owners | {v.viewer_id for v in seen_mine}
    names = await _usernames(db, people)
    urls = await _sign([s.storage_path for s in stories])
    streaks = {}
    if date is not None and owners:
        try:
            async with db.begin_nested():
                streaks = await streaks_with(db, user_id, list(owners), resolve_today(date))
        except Exception as exc:  # noqa: BLE001 - ordering only; never worth failing the feed
            log.warning("could not load streaks for stories: %r", exc)
    pictures = await avatars.avatar_urls(db, people)
    background.add_task(purge_expired_stories)

    viewers: dict[uuid.UUID, list] = {}
    for v in sorted(seen_mine, key=lambda v: v.viewed_at, reverse=True):
        if v.viewer_id in names:
            viewers.setdefault(v.story_id, []).append({
                "user_id": v.viewer_id, "username": names[v.viewer_id],
                "avatar_url": pictures.get(v.viewer_id), "reaction": v.reaction,
            })

    mine, by_owner = [], {}
    for s in stories:
        if s.user_id == user_id:
            mine.append({
                "story_id": s.id, "caption": s.caption, "created_at": s.created_at, "expires_at": s.expires_at,
                "image_url": urls.get(s.storage_path), "viewers": viewers.get(s.id, []),
            })
        elif s.user_id in names:  # can't show someone with no name
            view = my_views.get(s.id)
            by_owner.setdefault(s.user_id, []).append({
                "story_id": s.id, "caption": s.caption, "created_at": s.created_at, "expires_at": s.expires_at,
                "image_url": urls.get(s.storage_path), "viewed": view is not None,
                "reaction": view.reaction if view else None,
            })

    groups = [
        {
            "user_id": owner, "username": names[owner], "avatar_url": pictures.get(owner),
            "streak": streaks[owner].count if owner in streaks else 0,
            "all_seen": all(s["viewed"] for s in items), "stories": items,
        }
        for owner, items in by_owner.items()
    ]
    newest = lambda g: max(s["created_at"] for s in g["stories"])  # noqa: E731
    groups.sort(key=newest, reverse=True)
    groups.sort(key=lambda g: (g["all_seen"], -g["streak"]))  # stable: newest first within ties
    return {"mine": mine, "friends": groups}


async def _friends_live_story(db: AsyncSession, story_id: uuid.UUID, me: uuid.UUID) -> uuid.UUID:
    """The owner of a live story that [me] is allowed to see, or 404."""
    owner = (
        await db.execute(select(Story.user_id).where(Story.id == story_id, Story.expires_at > _now()))
    ).scalar_one_or_none()
    if owner is None or owner == me:
        raise HTTPException(404, GONE)
    linked = (
        await db.execute(
            select(Friendship.id).where(
                Friendship.status == "accepted",
                or_(
                    and_(Friendship.requester_id == me, Friendship.addressee_id == owner),
                    and_(Friendship.requester_id == owner, Friendship.addressee_id == me),
                ),
            )
        )
    ).scalar_one_or_none()
    if linked is None:
        raise HTTPException(404, GONE)
    return owner


@router.post("/{story_id}/view", status_code=204)
async def mark_viewed(
    story_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    await _friends_live_story(db, story_id, user_id)
    await db.execute(
        pg_insert(StoryView).values(story_id=story_id, viewer_id=user_id, viewed_at=_now()).on_conflict_do_nothing()
    )
    await db.commit()
    return None


@router.post("/{story_id}/react", status_code=204)
async def react(
    story_id: uuid.UUID,
    data: ReactIn,
    background: BackgroundTasks,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    if data.emoji not in REACTIONS:
        raise HTTPException(422, "That reaction isn't available.")
    owner = await _friends_live_story(db, story_id, user_id)
    now = _now()
    await db.execute(
        pg_insert(StoryView)
        .values(story_id=story_id, viewer_id=user_id, viewed_at=now, reaction=data.emoji, reacted_at=now)
        .on_conflict_do_update(
            index_elements=[StoryView.story_id, StoryView.viewer_id],
            set_={"reaction": data.emoji, "reacted_at": now},
        )
    )
    await db.commit()
    my_name = (await _usernames(db, [user_id])).get(user_id, "A friend")
    background.add_task(
        notify_user, owner, Kind.REACTION,
        dedupe_key=f"story-react:{story_id}:{user_id}:{data.emoji}", name=my_name, emoji=data.emoji,
    )
    background.add_task(record_activity, owner, "reaction", user_id, emoji=data.emoji, dedupe_key=f"story-react:{story_id}:{user_id}:{data.emoji}")
    return None


@router.post("/{story_id}/report", status_code=204)
async def report(
    story_id: uuid.UUID,
    data: ReportIn,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Report a friend's story. The team reviews reports in the database."""
    owner = await _friends_live_story(db, story_id, user_id)
    db.add(ContentReport(
        reporter_id=user_id, reported_user_id=owner, kind="story", subject_id=story_id,
        reason=(data.reason or "").strip() or None,
    ))
    await db.commit()
    return None


@router.delete("/{story_id}", status_code=204)
async def delete_story(
    story_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Take a photo off your story."""
    _require_storage()
    path = (
        await db.execute(select(Story.storage_path).where(Story.id == story_id, Story.user_id == user_id))
    ).scalar_one_or_none()
    if path is None:
        raise HTTPException(404, "That story isn't there any more.")
    try:
        await storage_service.delete([path])
    except StorageUnavailable:
        raise HTTPException(502, "Couldn't delete that story. Please try again.")
    await db.execute(delete(Story).where(Story.id == story_id))
    await db.commit()
    return None
