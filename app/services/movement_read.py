"""A best-effort read of this week's movement, for the coach and Insights
(roadmap R9). Own savepoint and never raises: the table may not exist yet
(migration not run) and the line it feeds is a nicety."""

import logging
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.movement import MovementLog
from app.services import movement

log = logging.getLogger("calorie_backend")

NOTHING = {"today_minutes": 0, "week_minutes": 0, "active_days": 0, "sessions": 0}


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
        return {
            "today_minutes": week["today_minutes"], "week_minutes": week["minutes"],
            "active_days": week["active_days"], "sessions": week["sessions"],
        }
    except Exception:  # noqa: BLE001
        log.warning("could not read this week's movement", exc_info=True)
        return dict(NOTHING)
