import base64
import binascii
import logging
import secrets
import uuid
from datetime import date as date_type, datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dates import resolve_today
from app.core.database import async_session_maker, get_db
from app.core.security import get_current_user_id
from app.models.friendship import Friendship
from app.models.snap import Snap, SnapDay, SnapRecipient, SnapReport
from app.models.user import Profile
from app.schemas.snaps import (
    REACTIONS,
    InboxSnapOut,
    ReactIn,
    ReportIn,
    SentSnapOut,
    SnapIn,
    SnapSentOut,
)
from app.services import storage_service
from app.services.notification_rules import Kind
from app.services.notifier import notify_user
from app.services.snap_streaks import streaks_with
from app.services.storage_service import StorageUnavailable

log = logging.getLogger("calorie_backend")

router = APIRouter(prefix="/snaps", tags=["snaps"])

SNAP_LIFETIME = timedelta(hours=24)
NOT_SET_UP = "Bites aren't available right now. Please try again later."


def image_type(data: bytes) -> tuple[str, str] | None:
    """(mime type, file extension) from the magic bytes, or None if it is not
    a JPEG, PNG or WebP. Never trust the client's label."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "webp"
    return None


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
        log.exception("could not sign snap links")
        return {p: None for p in paths}  # photos show a placeholder; the list still loads


async def purge_expired(limit: int = 100) -> int:
    """Delete expired snaps: the photo from storage, then the rows. Runs in
    the background after a read, and from POST /snaps/purge. Streak history
    (snap_days) is kept on purpose."""
    try:
        async with async_session_maker() as db:
            rows = (
                await db.execute(
                    select(Snap.id, Snap.storage_path).where(Snap.expires_at <= _now()).limit(limit)
                )
            ).all()
            if not rows:
                return 0
            await storage_service.delete([p for _, p in rows])
            await db.execute(delete(Snap).where(Snap.id.in_([i for i, _ in rows])))
            await db.commit()
            return len(rows)
    except Exception:  # noqa: BLE001 - housekeeping must never break a request
        log.exception("purging expired snaps failed")
        return 0


async def _recipient_summaries(db, me, recipient_ids, today, completed_now: bool):
    names = await _usernames(db, recipient_ids)
    streaks = await streaks_with(db, me, list(recipient_ids), today)
    return [
        {
            "user_id": uid,
            "username": names.get(uid, ""),
            "streak": streaks[uid].count,
            "completed_today": completed_now and streaks[uid].complete_today,
        }
        for uid in recipient_ids
    ]


@router.post("", response_model=SnapSentOut)
async def send_snap(
    data: SnapIn,
    background: BackgroundTasks,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Send a food photo to one or more friends. Repeating the same request
    (same id) is harmless: it returns the original result."""
    _require_storage()
    today = resolve_today(data.date)
    recipients = list(dict.fromkeys(data.recipient_ids))  # drop duplicates, keep order
    if user_id in recipients:
        raise HTTPException(422, "You can't send a bite to yourself.")

    existing = (await db.execute(select(Snap).where(Snap.id == data.id))).scalar_one_or_none()
    if existing is not None:
        if existing.sender_id != user_id:
            raise HTTPException(409, "That bite id is already used.")
        sent_to = (
            await db.execute(select(SnapRecipient.recipient_id).where(SnapRecipient.snap_id == data.id))
        ).scalars().all()
        return {
            "snap_id": existing.id,
            "expires_at": existing.expires_at,
            "recipients": await _recipient_summaries(db, user_id, sent_to, today, completed_now=False),
        }

    # Size first: decoding an unbounded payload could pin a lot of memory.
    if len(data.image) > settings.max_snap_bytes * 4 // 3 + 1024:
        raise HTTPException(413, "That photo is too large.")
    try:
        image = base64.b64decode(data.image, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(400, "That photo couldn't be read.")
    if not image or len(image) > settings.max_snap_bytes:
        raise HTTPException(413 if image else 400, "That photo is too large." if image else "That photo is empty.")
    kind = image_type(image)
    if kind is None:
        raise HTTPException(415, "Only JPEG, PNG or WebP photos can be sent.")
    mime, ext = kind

    if not set(recipients) <= await _friend_ids(db, user_id):
        raise HTTPException(403, "You can only send bites to your friends.")

    path = f"{user_id}/{data.id}.{ext}"
    try:
        await storage_service.upload(path, image, mime)
    except StorageUnavailable:
        log.exception("snap upload failed")
        raise HTTPException(502, "Couldn't upload that photo. Please try again.")

    expires = _now() + SNAP_LIFETIME
    try:
        db.add(Snap(
            id=data.id, sender_id=user_id, storage_path=path,
            caption=(data.caption or "").strip() or None, expires_at=expires,
        ))
        await db.flush()
        db.add_all(SnapRecipient(snap_id=data.id, recipient_id=r) for r in recipients)
        await db.execute(
            pg_insert(SnapDay)
            .values([{"sender_id": user_id, "recipient_id": r, "day": today} for r in recipients])
            .on_conflict_do_nothing()
        )
        await db.commit()
    except Exception:
        await db.rollback()
        log.exception("saving snap failed")
        try:
            await storage_service.delete([path])
        except StorageUnavailable:
            pass
        raise HTTPException(500, "Couldn't send that bite. Please try again.")

    summaries = await _recipient_summaries(db, user_id, recipients, today, completed_now=True)
    sender_name = (await _usernames(db, [user_id])).get(user_id, "A friend")
    for r in recipients:
        # After the response, and never allowed to fail the send.
        background.add_task(notify_user, r, Kind.FRIEND_SNAP, dedupe_key=f"snap:{data.id}", name=sender_name)
    return {"snap_id": data.id, "expires_at": expires, "recipients": summaries}


@router.get("/inbox", response_model=list[InboxSnapOut])
async def inbox(
    background: BackgroundTasks,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Snaps friends sent you in the last 24 hours, newest first."""
    _require_storage()
    rows = (
        await db.execute(
            select(Snap, SnapRecipient)
            .join(SnapRecipient, SnapRecipient.snap_id == Snap.id)
            .where(SnapRecipient.recipient_id == user_id, Snap.expires_at > _now())
            .order_by(Snap.created_at.desc())
        )
    ).all()
    # Only people who are still friends: unfriending or blocking hides their snaps.
    friends = await _friend_ids(db, user_id)
    rows = [(s, r) for s, r in rows if s.sender_id in friends]
    names = await _usernames(db, {s.sender_id for s, _ in rows})
    urls = await _sign([s.storage_path for s, _ in rows])
    background.add_task(purge_expired)
    return [
        {
            "snap_id": s.id,
            "sender_id": s.sender_id,
            "sender_username": names.get(s.sender_id, ""),
            "caption": s.caption,
            "created_at": s.created_at,
            "expires_at": s.expires_at,
            "viewed": r.viewed_at is not None,
            "reaction": r.reaction,
            "image_url": urls.get(s.storage_path),
        }
        for s, r in rows
    ]


@router.get("/sent", response_model=list[SentSnapOut])
async def sent(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Your own snaps from the last 24 hours, with who opened and reacted."""
    _require_storage()
    snaps = (
        await db.execute(
            select(Snap).where(Snap.sender_id == user_id, Snap.expires_at > _now()).order_by(Snap.created_at.desc())
        )
    ).scalars().all()
    if not snaps:
        return []
    recips = (
        await db.execute(select(SnapRecipient).where(SnapRecipient.snap_id.in_([s.id for s in snaps])))
    ).scalars().all()
    names = await _usernames(db, {r.recipient_id for r in recips})
    urls = await _sign([s.storage_path for s in snaps])
    by_snap: dict[uuid.UUID, list] = {}
    for r in recips:
        by_snap.setdefault(r.snap_id, []).append(
            {
                "user_id": r.recipient_id,
                "username": names.get(r.recipient_id, ""),
                "viewed": r.viewed_at is not None,
                "reaction": r.reaction,
            }
        )
    return [
        {
            "snap_id": s.id,
            "caption": s.caption,
            "created_at": s.created_at,
            "expires_at": s.expires_at,
            "image_url": urls.get(s.storage_path),
            "recipients": by_snap.get(s.id, []),
        }
        for s in snaps
    ]


async def _received_from(db: AsyncSession, snap_id: uuid.UUID, me: uuid.UUID) -> uuid.UUID:
    """The sender of a live snap addressed to [me], or 404."""
    sender = (
        await db.execute(
            select(Snap.sender_id)
            .join(SnapRecipient, SnapRecipient.snap_id == Snap.id)
            .where(Snap.id == snap_id, SnapRecipient.recipient_id == me, Snap.expires_at > _now())
        )
    ).scalar_one_or_none()
    if sender is None:
        raise HTTPException(404, "That bite has disappeared.")
    return sender


@router.post("/{snap_id}/view", status_code=204)
async def mark_viewed(
    snap_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    await _received_from(db, snap_id, user_id)
    await db.execute(
        update(SnapRecipient)
        .where(SnapRecipient.snap_id == snap_id, SnapRecipient.recipient_id == user_id,
               SnapRecipient.viewed_at.is_(None))
        .values(viewed_at=_now())
    )
    await db.commit()
    return None


@router.post("/{snap_id}/react", status_code=204)
async def react(
    snap_id: uuid.UUID,
    data: ReactIn,
    background: BackgroundTasks,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    if data.emoji not in REACTIONS:
        raise HTTPException(422, "That reaction isn't available.")
    sender = await _received_from(db, snap_id, user_id)
    await db.execute(
        update(SnapRecipient)
        .where(SnapRecipient.snap_id == snap_id, SnapRecipient.recipient_id == user_id)
        .values(reaction=data.emoji, reacted_at=_now())
    )
    await db.commit()
    my_name = (await _usernames(db, [user_id])).get(user_id, "A friend")
    background.add_task(
        notify_user, sender, Kind.REACTION, dedupe_key=f"react:{snap_id}:{user_id}:{data.emoji}", name=my_name, emoji=data.emoji
    )
    return None


@router.post("/{snap_id}/report", status_code=204)
async def report(
    snap_id: uuid.UUID,
    data: ReportIn,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Report a snap you received. The team reviews reports in the database."""
    sender = await _received_from(db, snap_id, user_id)
    db.add(SnapReport(
        reporter_id=user_id, reported_user_id=sender, snap_id=snap_id,
        reason=(data.reason or "").strip() or None,
    ))
    await db.commit()
    return None


@router.delete("/{snap_id}", status_code=204)
async def delete_snap(
    snap_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Take back a snap you sent. The day still counts toward the streak."""
    _require_storage()
    path = (
        await db.execute(select(Snap.storage_path).where(Snap.id == snap_id, Snap.sender_id == user_id))
    ).scalar_one_or_none()
    if path is None:
        raise HTTPException(404, "That bite isn't there any more.")
    try:
        await storage_service.delete([path])
    except StorageUnavailable:
        raise HTTPException(502, "Couldn't delete that bite. Please try again.")
    await db.execute(delete(Snap).where(Snap.id == snap_id))
    await db.commit()
    return None


@router.post("/purge")
async def purge(x_cron_secret: str | None = Header(default=None)):
    """For a scheduler: delete every expired snap. Disabled until CRON_SECRET is set."""
    if not settings.cron_secret:
        raise HTTPException(404, "Not found")
    if not x_cron_secret or not secrets.compare_digest(x_cron_secret, settings.cron_secret):
        raise HTTPException(403, "Forbidden")
    _require_storage()
    return {"purged": await purge_expired(limit=500)}
