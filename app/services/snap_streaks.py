import uuid
from datetime import date, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.snap import SnapDay
from app.services.pair_streak import PairStreak, pair_streak

# Far longer than any streak the app will see soon, and keeps the query small.
LOOKBACK_DAYS = 400


async def streaks_with(
    db: AsyncSession, me: uuid.UUID, friend_ids: list[uuid.UUID], today: date
) -> dict[uuid.UUID, PairStreak]:
    """The pair streak between [me] and each of [friend_ids]."""
    if not friend_ids:
        return {}
    since = today - timedelta(days=LOOKBACK_DAYS)
    rows = (
        await db.execute(
            select(SnapDay.sender_id, SnapDay.recipient_id, SnapDay.day).where(
                SnapDay.day >= since,
                or_(
                    and_(SnapDay.sender_id == me, SnapDay.recipient_id.in_(friend_ids)),
                    and_(SnapDay.recipient_id == me, SnapDay.sender_id.in_(friend_ids)),
                ),
            )
        )
    ).all()

    mine: dict[uuid.UUID, set[date]] = {f: set() for f in friend_ids}
    theirs: dict[uuid.UUID, set[date]] = {f: set() for f in friend_ids}
    for sender, recipient, day in rows:
        if sender == me:
            mine[recipient].add(day)
        else:
            theirs[sender].add(day)
    return {f: pair_streak(mine[f], theirs[f], today) for f in friend_ids}
