"""Direct messages between friends: text only, one conversation per pair.

Only accepted friends can message each other. Blocking or unfriending removes
the friendship, so the conversation disappears from both phones and nothing
more can be sent; the rows stay, so becoming friends again restores it.
"""

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, case, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rate_limit import messages_sent
from app.core.security import get_current_user_id
from app.models.friendship import Friendship
from app.models.message import Message, MessageAttachment
from app.models.story import ContentReport
from app.models.user import Profile
from app.schemas.messages import ConversationOut, ConversationsOut, MessageIn, MessageOut, ThreadOut
from app.schemas.snaps import ReportIn
from app.services import avatars

log = logging.getLogger("calorie_backend")

router = APIRouter(prefix="/messages", tags=["messages"])

PAGE = 50
NOT_FRIENDS = "You can only message your friends."


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _pair(me: uuid.UUID, other: uuid.UUID):
    return or_(
        and_(Message.sender_id == me, Message.recipient_id == other),
        and_(Message.sender_id == other, Message.recipient_id == me),
    )


def _out(m: Message, me: uuid.UUID, attachment: dict | None = None) -> MessageOut:
    mine = m.sender_id == me
    return MessageOut(
        id=m.id, mine=mine, body=m.body, created_at=m.created_at, read_at=m.read_at if mine else None,
        attachment=attachment,
    )


async def load_attachments(db: AsyncSession, message_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict]:
    """Cards attached to these messages. In a savepoint and forgiving: if the
    table isn't there yet, chat just shows the plain text."""
    if not message_ids:
        return {}
    try:
        async with db.begin_nested():
            rows = (
                await db.execute(
                    select(MessageAttachment.message_id, MessageAttachment.attachment).where(
                        MessageAttachment.message_id.in_(message_ids)
                    )
                )
            ).all()
        return {mid: att for mid, att in rows if att}
    except Exception:  # noqa: BLE001
        log.warning("could not read message attachments", exc_info=True)
        return {}


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


async def _require_friend(db: AsyncSession, me: uuid.UUID, other: uuid.UUID) -> None:
    if me == other:
        raise HTTPException(422, "You can't message yourself.")
    found = (
        await db.execute(
            select(Friendship.id).where(
                Friendship.status == "accepted",
                or_(
                    and_(Friendship.requester_id == me, Friendship.addressee_id == other),
                    and_(Friendship.requester_id == other, Friendship.addressee_id == me),
                ),
            )
        )
    ).first()
    if found is None:
        raise HTTPException(403, NOT_FRIENDS)


@router.get("", response_model=ConversationsOut)
async def conversations(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Your conversations with current friends, newest first, with how many
    messages in each you haven't opened. Also what the unread badge uses."""
    friends = await _friend_ids(db, user_id)
    if not friends:
        return ConversationsOut(conversations=[], unread_total=0)

    other = case((Message.sender_id == user_id, Message.recipient_id), else_=Message.sender_id)
    last = (
        await db.execute(
            select(other, Profile.username, Message.body, Message.sender_id, Message.created_at)
            .ext(distinct_on(other))
            .join(Profile, Profile.id == other)
            .where(or_(Message.sender_id == user_id, Message.recipient_id == user_id), other.in_(friends))
            .order_by(other, Message.created_at.desc())
        )
    ).all()
    unread = dict(
        (
            await db.execute(
                select(Message.sender_id, func.count())
                .where(Message.recipient_id == user_id, Message.read_at.is_(None), Message.sender_id.in_(friends))
                .group_by(Message.sender_id)
            )
        ).all()
    )
    pictures = await avatars.avatar_urls(db, [row[0] for row in last])

    items = sorted(
        (
            ConversationOut(
                user_id=who, username=name, avatar_url=pictures.get(who), last_body=body,
                last_mine=sender == user_id, last_at=at, unread=int(unread.get(who, 0)),
            )
            for who, name, body, sender, at in last
        ),
        key=lambda c: c.last_at,
        reverse=True,
    )
    return ConversationsOut(conversations=items, unread_total=sum(c.unread for c in items))


@router.get("/with/{friend_id}", response_model=ThreadOut)
async def thread(
    friend_id: uuid.UUID,
    before: datetime | None = Query(None, description="Only messages older than this (to load earlier ones)"),
    limit: int = Query(PAGE, ge=1, le=100),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """The latest messages with a friend, oldest first."""
    await _require_friend(db, user_id, friend_id)
    query = select(Message).where(_pair(user_id, friend_id))
    if before is not None:
        query = query.where(Message.created_at < before)
    rows = (
        await db.execute(query.order_by(Message.created_at.desc(), Message.id.desc()).limit(limit + 1))
    ).scalars().all()
    more = len(rows) > limit
    rows = list(reversed(rows[:limit]))
    attachments = await load_attachments(db, [m.id for m in rows])
    return ThreadOut(messages=[_out(m, user_id, attachments.get(m.id)) for m in rows], has_more=more)


@router.post("/with/{friend_id}", response_model=MessageOut)
async def send(
    friend_id: uuid.UUID,
    data: MessageIn,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Send a message to a friend. Repeating the same request (same id) is
    harmless: it returns the original."""
    existing = (await db.execute(select(Message).where(Message.id == data.id))).scalar_one_or_none()
    if existing is not None:
        if existing.sender_id != user_id or existing.recipient_id != friend_id:
            raise HTTPException(409, "That message id is already used.")
        return _out(existing, user_id)

    await _require_friend(db, user_id, friend_id)
    messages_sent.check("message", user_id, "You're sending messages very fast. Try again in a moment.")

    message = Message(id=data.id, sender_id=user_id, recipient_id=friend_id, body=data.body, created_at=_now())
    db.add(message)
    try:
        await db.commit()
    except IntegrityError:
        # The same id arrived twice at once: the first one won.
        await db.rollback()
        again = (await db.execute(select(Message).where(Message.id == data.id))).scalar_one_or_none()
        if again is None or again.sender_id != user_id:
            raise HTTPException(409, "That message id is already used.")
        return _out(again, user_id)
    return _out(message, user_id)


@router.post("/with/{friend_id}/read", status_code=204)
async def mark_read(
    friend_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """You opened the conversation: everything they sent is now read."""
    await db.execute(
        update(Message)
        .where(Message.sender_id == friend_id, Message.recipient_id == user_id, Message.read_at.is_(None))
        .values(read_at=_now())
    )
    await db.commit()
    return None


@router.delete("/{message_id}", status_code=204)
async def unsend(
    message_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Delete a message you sent, for both of you."""
    result = await db.execute(delete(Message).where(Message.id == message_id, Message.sender_id == user_id))
    if not result.rowcount:
        raise HTTPException(404, "That message isn't there any more.")
    await db.commit()
    return None


@router.post("/{message_id}/report", status_code=204)
async def report(
    message_id: uuid.UUID,
    data: ReportIn,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Report a message you received. The team reviews reports in the
    database. The text is copied into the report, because the sender could
    delete the message afterwards."""
    message = (
        await db.execute(select(Message).where(Message.id == message_id, Message.recipient_id == user_id))
    ).scalar_one_or_none()
    if message is None:
        raise HTTPException(404, "That message isn't there any more.")
    reason = (data.reason or "").strip()
    db.add(ContentReport(
        reporter_id=user_id, reported_user_id=message.sender_id, kind="message", subject_id=message_id,
        reason=" | ".join(x for x in (reason, f"message: {message.body[:300]}") if x),
    ))
    await db.commit()
    return None
