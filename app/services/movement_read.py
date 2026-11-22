"""A best-effort read of this week's movement, for the coach and Insights
(roadmap R9). Own savepoint and never raises: the table may not exist yet
(migration not run) and the line it feeds is a nicety."""

import logging
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import func

from app.models.movement import MovementLog, MovementPrefs
from app.services import movement

log = logging.getLogger("calorie_backend")

NOTHING = {"today_minutes": 0, "week_minutes": 0, "active_days": 0, "sessions": 0, "eat_back_kcal": 0}


async def week_snapshot(db: AsyncSession, user_id: uuid.UUID, today: date) -> dict:
    """{today_minutes, week_minutes, active_days, sessions} for the week [today] is in."""
    try:
        start = movement.week_start(today)
        async with db.begin_nested():
            result = await db.execute(
                select(MovementLog.log_date, MovementLog.slice, MovementLog.minutes).where(
                    MovementLog.user_id == user_id, MovementLog.log_date >= start, MovementLog.log_date <= today
                )
            )
            rows = [(d, s, int(m)) for d, s, m in result.all()]
        week = movement.summarise_week(rows, today)
        snapshot = {
            "today_minutes": week["today_minutes"], "week_minutes": week["minutes"],
            "active_days": week["active_days"], "sessions": week["sessions"], "eat_back_kcal": 0,
        }
    except Exception:  # noqa: BLE001
        log.warning("could not read this week's movement", exc_info=True)
        return dict(NOTHING)
    # The opt-in share added to today's plan, so the coach and Insights quote the
    # same number the home ring shows. Its own guarded read (0 when off).
    _, snapshot["eat_back_kcal"] = await today_eat_back(db, user_id, today)
    return snapshot


async def eat_back_percent(db: AsyncSession, user_id: uuid.UUID) -> int:
    """The person's choice (0 = off). Own savepoint, never raises; 0 without the table."""
    try:
        async with db.begin_nested():
            value = (
                await db.execute(select(MovementPrefs.eat_back_percent).where(MovementPrefs.user_id == user_id))
            ).scalar_one_or_none()
        return max(0, min(movement.EAT_BACK_MAX_PERCENT, int(value or 0)))
    except Exception:  # noqa: BLE001
        log.warning("could not read the movement prefs", exc_info=True)
        return 0


async def today_eat_back(db: AsyncSession, user_id: uuid.UUID, today: date) -> tuple[int, int]:
    """(percent, kcal added to today's plan). Reads today's estimates only when the
    choice is on, so people who never turned it on cost nothing extra."""
    percent = await eat_back_percent(db, user_id)
    if percent <= 0:
        return 0, 0
    try:
        async with db.begin_nested():
            total = (
                await db.execute(
                    select(func.coalesce(func.sum(MovementLog.est_kcal), 0)).where(
                        MovementLog.user_id == user_id, MovementLog.log_date == today
                    )
                )
            ).scalar_one_or_none()
        return percent, movement.eat_back_kcal(percent, int(total or 0))
    except Exception:  # noqa: BLE001
        log.warning("could not add up today's movement estimates", exc_info=True)
        return percent, 0
