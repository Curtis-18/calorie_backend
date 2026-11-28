"""Loads what the progress maths needs for one person, in one place.

The Progress screen (GET /progress) and the hourly badge/level notifications
both read through here, so a "new badge" notification can never disagree with
what the app shows.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.food_log import FoodLog
from app.models.target import Target
from app.models.weight_log import WeightLog
from app.services.progress_service import LogRow, compute_progress


@dataclass(frozen=True)
class ProgressInputs:
    rows: list[LogRow]
    calorie_target: int | None
    protein_target: int | None
    weigh_in_dates: list[date]


async def load_inputs(db: AsyncSession, user_id: uuid.UUID, today: date) -> ProgressInputs:
    """Everything up to and including [today] (the person's own day)."""
    result = await db.execute(
        select(
            FoodLog.log_date,
            FoodLog.meal_type,
            FoodLog.source,
            FoodLog.calories,
            FoodLog.protein_g,
            FoodLog.timestamp,
        ).where(FoodLog.user_id == user_id, FoodLog.log_date <= today)
    )
    rows = [LogRow(*row) for row in result.all()]

    target = (
        await db.execute(select(Target.calorie_target, Target.protein_g).where(Target.user_id == user_id))
    ).first()

    weigh_in_dates: list[date] = []
    try:
        async with db.begin_nested():  # weight_logs may not exist before the migration
            weigh_in_dates = list(
                (
                    await db.execute(
                        select(WeightLog.log_date).where(WeightLog.user_id == user_id, WeightLog.log_date <= today)
                    )
                ).scalars()
            )
    except Exception:  # noqa: BLE001 - progress without weigh-ins beats an error
        weigh_in_dates = []

    return ProgressInputs(
        rows=rows,
        calorie_target=target[0] if target else None,
        protein_target=target[1] if target else None,
        weigh_in_dates=weigh_in_dates,
    )


def progress_on(inputs: ProgressInputs, day: date, lang: str = "en") -> dict:
    """The progress as it stood at the end of [day] (any day up to the one the
    inputs were loaded for: later logs are ignored by compute_progress)."""
    return compute_progress(
        inputs.rows,
        today=day,
        calorie_target=inputs.calorie_target,
        protein_target=inputs.protein_target,
        weigh_in_dates=inputs.weigh_in_dates,
        lang=lang,
    )


async def load_progress(db: AsyncSession, user_id: uuid.UUID, today: date, lang: str = "en") -> dict:
    return progress_on(await load_inputs(db, user_id, today), today, lang)
