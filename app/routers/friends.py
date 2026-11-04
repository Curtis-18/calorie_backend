import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user_id
from app.models.friendship import Block, Friendship
from app.models.user import Profile
from app.schemas.friends import FriendRequestIn, FriendsOut, PersonOut, RequestResultOut
from app.services.friends_service import (
    FRIEND_LIMIT,
    MESSAGES,
    ExistingLink,
    Outcome,
    RequestFacts,
    can_accept,
    decide_request,
)
from app.services.username_service import validate_username

log = logging.getLogger("calorie_backend")

router = APIRouter(tags=["friends"])

_STATUS = {
    Outcome.NOT_FOUND: 404,
    Outcome.SELF: 422,
    Outcome.ME_AT_LIMIT: 409,
    Outcome.THEM_AT_LIMIT: 409,
    Outcome.TOO_MANY_PENDING: 429,
}


def _involves(user_id: uuid.UUID):
    return or_(Friendship.requester_id == user_id, Friendship.addressee_id == user_id)


async def _friend_count(db: AsyncSession, user_id: uuid.UUID) -> int:
    return (
        await db.execute(
            select(func.count()).select_from(Friendship).where(
                Friendship.status == "accepted", _involves(user_id)
            )
        )
    ).scalar_one()


async def _gather(db: AsyncSession, me: uuid.UUID, name: str):
    """Everything decide_request needs, plus the pending row (to accept) and
    the target's username as stored."""
    mine = (await db.execute(select(Profile.username).where(Profile.id == me))).scalar_one_or_none()
    if mine is None:
        raise HTTPException(409, "Pick a username before adding friends.")

    target_id, target_name = None, None
    if validate_username(name) is None:
        row = (
            await db.execute(
                select(Profile.id, Profile.username).where(func.lower(Profile.username) == name.strip().lower())
            )
        ).first()
        if row:
            target_id, target_name = row

    if target_id is None:
        return RequestFacts(me, None, False, None, 0, 0, 0), None, None

    blocked = (
        await db.execute(
            select(Block.blocker_id).where(
                or_(
                    and_(Block.blocker_id == me, Block.blocked_id == target_id),
                    and_(Block.blocker_id == target_id, Block.blocked_id == me),
                )
            ).limit(1)
        )
    ).first() is not None

    link = (
        await db.execute(
            select(Friendship).where(
                or_(
                    and_(Friendship.requester_id == me, Friendship.addressee_id == target_id),
                    and_(Friendship.requester_id == target_id, Friendship.addressee_id == me),
                )
            )
        )
    ).scalar_one_or_none()

    pending_out = (
        await db.execute(
            select(func.count()).select_from(Friendship).where(
                Friendship.requester_id == me, Friendship.status == "pending"
            )
        )
    ).scalar_one()

    facts = RequestFacts(
        me=me,
        target=target_id,
        blocked_either_way=blocked,
        existing=ExistingLink(link.requester_id, link.status) if link else None,
        my_friends=await _friend_count(db, me),
        their_friends=await _friend_count(db, target_id),
        my_pending_out=pending_out,
    )
    return facts, link, target_name


@router.get("/friends", response_model=FriendsOut)
async def list_friends(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(select(Friendship).where(_involves(user_id)))).scalars().all()
    others = {r.addressee_id if r.requester_id == user_id else r.requester_id for r in rows}
    names = {}
    if others:
        names = dict(
            (await db.execute(select(Profile.id, Profile.username).where(Profile.id.in_(others)))).all()
        )

    friends, incoming, outgoing = [], [], []
    for r in rows:
        other = r.addressee_id if r.requester_id == user_id else r.requester_id
        username = names.get(other)
        if not username:  # can't show someone with no name
            continue
        person = PersonOut(
            friendship_id=r.id, user_id=other, username=username,
            since=r.responded_at or r.created_at,
        )
        if r.status == "accepted":
            friends.append(person)
        elif r.requester_id == user_id:
            outgoing.append(person)
        else:
            incoming.append(person)

    friends.sort(key=lambda p: p.username.lower())
    incoming.sort(key=lambda p: p.since, reverse=True)
    outgoing.sort(key=lambda p: p.since, reverse=True)
    return {"friends": friends, "incoming": incoming, "outgoing": outgoing, "limit": FRIEND_LIMIT}


@router.post("/friends/requests", response_model=RequestResultOut)
async def send_request(
    data: FriendRequestIn,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Ask someone (by exact username) to be friends. If they already asked
    you, this accepts. Repeating a request is harmless."""
    facts, link, target_name = await _gather(db, user_id, data.username)
    outcome = decide_request(facts)

    if outcome in _STATUS:
        raise HTTPException(_STATUS[outcome], MESSAGES[outcome])

    try:
        if outcome == Outcome.SEND:
            db.add(Friendship(requester_id=user_id, addressee_id=facts.target, status="pending"))
            await db.commit()
        elif outcome == Outcome.ACCEPT:
            await db.execute(
                update(Friendship)
                .where(Friendship.id == link.id)
                .values(status="accepted", responded_at=datetime.now(timezone.utc))
            )
            await db.commit()
    except IntegrityError:
        # Both of you asked at the same instant: the unique pair index won.
        await db.rollback()
        raise HTTPException(409, "Something changed while we were sending that. Please try again.")
    return {"outcome": outcome.value, "username": target_name}


@router.post("/friends/requests/{friendship_id}/accept", status_code=204)
async def accept_request(
    friendship_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(
            select(Friendship).where(
                Friendship.id == friendship_id,
                Friendship.addressee_id == user_id,
                Friendship.status == "pending",
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "That request isn't there any more.")

    blocked = can_accept(await _friend_count(db, user_id), await _friend_count(db, row.requester_id))
    if blocked:
        raise HTTPException(409, MESSAGES[blocked])

    await db.execute(
        update(Friendship)
        .where(Friendship.id == friendship_id)
        .values(status="accepted", responded_at=datetime.now(timezone.utc))
    )
    await db.commit()
    return None


@router.post("/friends/requests/{friendship_id}/decline", status_code=204)
async def decline_request(
    friendship_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Quietly remove a request. The sender is not told."""
    result = await db.execute(
        delete(Friendship).where(
            Friendship.id == friendship_id,
            Friendship.addressee_id == user_id,
            Friendship.status == "pending",
        )
    )
    if result.rowcount == 0:
        raise HTTPException(404, "That request isn't there any more.")
    await db.commit()
    return None


@router.delete("/friends/{friendship_id}", status_code=204)
async def remove_friend(
    friendship_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Unfriend, or cancel a request you sent. Either side can do it."""
    result = await db.execute(
        delete(Friendship).where(Friendship.id == friendship_id, _involves(user_id))
    )
    if result.rowcount == 0:
        raise HTTPException(404, "They aren't on your list.")
    await db.commit()
    return None


@router.post("/friends/{friendship_id}/block", status_code=204)
async def block_person(
    friendship_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Block the other person in a friendship or request: it is removed, and
    neither of you can find or add the other again until you unblock."""
    row = (
        await db.execute(select(Friendship).where(Friendship.id == friendship_id, _involves(user_id)))
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "They aren't on your list.")
    other = row.addressee_id if row.requester_id == user_id else row.requester_id

    await db.execute(delete(Friendship).where(Friendship.id == friendship_id))
    await db.execute(
        pg_insert(Block).values(blocker_id=user_id, blocked_id=other).on_conflict_do_nothing()
    )
    await db.commit()
    return None


@router.get("/blocks", response_model=list[PersonOut])
async def list_blocks(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(Block.blocked_id, Profile.username, Block.created_at)
            .join(Profile, Profile.id == Block.blocked_id)
            .where(Block.blocker_id == user_id)
            .order_by(Block.created_at.desc())
        )
    ).all()
    return [
        PersonOut(user_id=uid, username=name, since=since) for uid, name, since in rows if name
    ]


@router.delete("/blocks/{blocked_id}", status_code=204)
async def unblock(
    blocked_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        delete(Block).where(Block.blocker_id == user_id, Block.blocked_id == blocked_id)
    )
    if result.rowcount == 0:
        raise HTTPException(404, "You haven't blocked them.")
    await db.commit()
    return None
