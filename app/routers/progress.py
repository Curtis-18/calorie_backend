import uuid
from datetime import date as date_type

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dates import resolve_today
from app.core.security import get_current_user_id
from app.models.food_log import FoodLog
from app.models.target import Target
from app.models.weight_log import WeightLog
from app.schemas.progress import ProgressOut
from app.services.progress_service import LogRow, compute_progress

router = APIRouter(prefix="/progress", tags=["progress"])


@router.get("", response_model=ProgressOut)
async def get_progress(
    date: date_type | None = None,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Streak, freezes, XP, level and achievements, derived from the logs.

    `date` is the device-local "today" (see resolve_today), so the streak
    agrees with the day the user is actually on.
    """
    today = resolve_today(date)

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

    target_result = await db.execute(
        select(Target.calorie_target, Target.protein_g).where(Target.user_id == user_id)
    )
    target = target_result.first()

    weigh_in_dates: list[date_type] = []
    try:
        async with db.begin_nested():  # weight_logs may not exist before the migration
            weigh_in_dates = list(
                (
                    await db.execute(
                        select(WeightLog.log_date).where(
                            WeightLog.user_id == user_id, WeightLog.log_date <= today
                        )
                    )
                ).scalars()
            )
    except Exception:  # noqa: BLE001 - progress without weigh-ins beats an error
        weigh_in_dates = []

    return compute_progress(
        rows,
        today=today,
        calorie_target=target[0] if target else None,
        protein_target=target[1] if target else None,
        weigh_in_dates=weigh_in_dates,
    )
