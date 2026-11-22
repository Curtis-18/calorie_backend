"""Direct messages between friends: text only, one conversation per pair.

Only accepted friends can message each other. Blocking or unfriending removes
the friendship, so the conversation disappears from both phones and nothing
more can be sent; the rows stay, so becoming friends again restores it.
"""

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import and_, case, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import aliased
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rate_limit import messages_sent
from app.core.security import get_current_user_id
from app.models.friendship import Friendship
from app.models.message import Message, MessageAttachment, MessageQuote
from app.models.story import ContentReport
from app.models.user import Profile
from app.schemas.messages import ConversationOut, ConversationsOut, MessageIn, MessageOut, QuoteOut, ThreadOut
from app.schemas.snaps import ReportIn
from app.services import avatars, recipe_photos
from app.services.notification_rules import Kind
from app.services.notifier import notify_from

log = logging.getLogger("calorie_backend")

router = APIRouter(prefix="/messages", tags=["messages"])

PAGE = 50
QUOTE_CHARS = 140
GONE = "That message isn't there any more."
NOT_FRIENDS = "You can only message your friends."


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _pair(me: uuid.UUID, other: uuid.UUID):
    return or_(
        and_(Message.sender_id == me, Message.recipient_id == other),
        and_(Message.sender_id == other, Message.recipient_id == me),
    )


def _out(m: Message, me: uuid.UUID, attachment: dict | None = None, quote: QuoteOut | None = None) -> MessageOut:
    mine = m.sender_id == me
    return MessageOut(
        id=m.id, mine=mine, body=m.body, created_at=m.created_at, read_at=m.read_at if mine else None,
        attachment=attachment, quote=quote,
    )


def _shorten(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= QUOTE_CHARS else text[: QUOTE_CHARS - 1].rstrip() + "\u2026"


async def load_quotes(db: AsyncSession, message_ids: list[uuid.UUID], me: uuid.UUID) -> dict[uuid.UUID, QuoteOut]:
    """What each of these messages replies to, one query. Forgiving like
    attachments: without the table, chat just shows the messages."""
    if not message_ids:
        return {}
    original = aliased(Message)
    try:
        async with db.begin_nested():
            rows = (
                await db.execute(
                    select(MessageQuote.message_id, original.id, original.sender_id, original.body)
                    .outerjoin(original, original.id == MessageQuote.quoted_id)
                    .where(MessageQuote.message_id.in_(message_ids))
                )
            ).all()
    except Exception:  # noqa: BLE001
        log.warning("could not read message quotes", exc_info=True)
        return {}
    out: dict[uuid.UUID, QuoteOut] = {}
    for message_id, quoted_id, quoted_sender, quoted_body in rows:
        if quoted_id is None:
            out[message_id] = QuoteOut(deleted=True)
        else:
            out[message_id] = QuoteOut(id=quoted_id, mine=quoted_sender == me, body=_shorten(quoted_body))
    return out


async def _save_quote(db: AsyncSession, message_id: uuid.UUID, quoted_id: uuid.UUID) -> bool:
    """Link the new message to the one it quotes. In a savepoint: if the table is
    missing the message is still sent, just without the quote."""
    try:
        async with db.begin_nested():
            await db.execute(pg_insert(MessageQuote).values(message_id=message_id, quoted_id=quoted_id).on_conflict_do_nothing())
        return True
    except Exception:  # noqa: BLE001
        log.warning("could not save the quote; sending the message without it", exc_info=True)
        return False


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
        found = {mid: att for mid, att in rows if att}
    except Exception:  # noqa: BLE001
        log.warning("could not read message attachments", exc_info=True)
        return {}
    return await _with_recipe_photos(db, found)


async def _with_recipe_photos(db: AsyncSession, found: dict[uuid.UUID, dict]) -> dict[uuid.UUID, dict]:
    """Put the recipe's cover on its card. The card is saved JSON and a photo link
    expires, so the link is made fresh each time a thread is read. No photo, a
    deleted recipe or any trouble just leaves the card as it was."""
    wanted: dict[uuid.UUID, uuid.UUID] = {}
    for mid, att in found.items():
        if att.get("kind") == "recipe":
            try:
                wanted[mid] = uuid.UUID(str(att.get("id")))
            except ValueError:
                continue
    if not wanted:
        return found
    try:
        links = await recipe_photos.covers(db, list(wanted.values()))
    except Exception:  # noqa: BLE001
        log.warning("could not read recipe covers for chat cards", exc_info=True)
        return found
    return {mid: ({**att, "photo_url": links[wanted[mid]]} if wanted.get(mid) in links else att) for mid, att in found.items()}


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
    quotes = await load_quotes(db, [m.id for m in rows], user_id)
    return ThreadOut(messages=[_out(m, user_id, attachments.get(m.id), quotes.get(m.id)) for m in rows], has_more=more)


@router.post("/with/{friend_id}", response_model=MessageOut)
async def send(
    friend_id: uuid.UUID,
    data: MessageIn,
    background: BackgroundTasks,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Send a message to a friend. Repeating the same request (same id) is
    harmless: it returns the original."""
    existing = (await db.execute(select(Message).where(Message.id == data.id))).scalar_one_or_none()
    if existing is not None:
        if existing.sender_id != user_id or existing.recipient_id != friend_id:
            raise HTTPException(409, "That message id is already used.")
        quotes = await load_quotes(db, [existing.id], user_id)
        return _out(existing, user_id, quote=quotes.get(existing.id))

    await _require_friend(db, user_id, friend_id)
    messages_sent.check("message", user_id, "You're sending messages very fast. Try again in a moment.")
    if data.reply_to is not None:
        # Only a message of this very conversation can be quoted: never someone
        # else's, so a guessed id reveals nothing.
        quoted = (
            await db.execute(select(Message.id).where(Message.id == data.reply_to, _pair(user_id, friend_id)))
        ).first()
        if quoted is None:
            raise HTTPException(404, GONE)

    message = Message(id=data.id, sender_id=user_id, recipient_id=friend_id, body=data.body, created_at=_now())
    db.add(message)
    quote_saved = False
    try:
        if data.reply_to is not None:
            await db.flush()  # the quote row refers to the message
            quote_saved = await _save_quote(db, data.id, data.reply_to)
        await db.commit()
    except IntegrityError:
        # The same id arrived twice at once: the first one won.
        await db.rollback()
        again = (await db.execute(select(Message).where(Message.id == data.id))).scalar_one_or_none()
        if again is None or again.sender_id != user_id:
            raise HTTPException(409, "That message id is already used.")
        quotes = await load_quotes(db, [again.id], user_id)
        return _out(again, user_id, quote=quotes.get(again.id))
    quote = (await load_quotes(db, [message.id], user_id)).get(message.id) if quote_saved else None
    # One nudge per sender per hour, so a back-and-forth is not a buzz per line,
    # and the text itself never goes into the notification (a lock screen).
    hour = datetime.now(timezone.utc).strftime("%Y%m%d%H")
    background.add_task(notify_from, friend_id, Kind.MESSAGE, user_id, dedupe_key=f"msg:{user_id}:{friend_id}:{hour}")
    return _out(message, user_id, quote=quote)


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
