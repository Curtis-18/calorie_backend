import uuid
from datetime import date as date_type, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dates import resolve_today
from app.core.features import Feature, require_feature
from app.core.security import get_current_user_id
from app.models.food_log import FoodLog
from app.models.target import Target
from app.services.patterns import WINDOW_DAYS, Entry, build_report

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/weekly")
async def weekly_report(
    date: date_type | None = None,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Your week in a few kind lines, plus any habit pattern the data supports.

    Derived on each call from the last four weeks of logs (nothing is stored),
    and written by code, not a language model, so it only ever states what the
    numbers show. Pro later (feature WEEKLY_REPORT); open to everyone today.
    """
    require_feature(user_id, Feature.WEEKLY_REPORT)
    today = resolve_today(date)
    rows = (
        await db.execute(
            select(FoodLog.log_date, FoodLog.timestamp, FoodLog.meal_type, FoodLog.calories, FoodLog.protein_g).where(
                FoodLog.user_id == user_id,
                FoodLog.log_date > today - timedelta(days=WINDOW_DAYS),
                FoodLog.log_date <= today,
            )
        )
    ).all()
    protein_target = (await db.execute(select(Target.protein_g).where(Target.user_id == user_id))).scalar_one_or_none()
    entries = [Entry(d, ts, meal, int(cal or 0), float(p or 0)) for d, ts, meal, cal, p in rows]
    return build_report(entries, today, protein_target)
