import logging
import uuid
from datetime import date as date_type, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dates import resolve_today
from app.core.features import Feature, require_feature
from app.core.language import get_language
from app.core.security import get_current_user_id
from app.models.food_log import FoodLog
from app.models.food_log_nutrients import FoodLogNutrients
from app.models.target import Target
from app.services.nutrients import FIBER_G_PER_1000_KCAL
from app.services.patterns import WINDOW_DAYS, Entry, build_report

log = logging.getLogger("calorie_backend")

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/weekly")
async def weekly_report(
    date: date_type | None = None,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
    lang: str = Depends(get_language),
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
            select(
                FoodLog.log_date, FoodLog.timestamp, FoodLog.meal_type, FoodLog.calories, FoodLog.protein_g, FoodLog.id
            ).where(
                FoodLog.user_id == user_id,
                FoodLog.log_date > today - timedelta(days=WINDOW_DAYS),
                FoodLog.log_date <= today,
            )
        )
    ).all()
    target = (
        await db.execute(
            select(Target.protein_g, Target.calorie_target).where(Target.user_id == user_id)
        )
    ).one_or_none()
    protein_target = target[0] if target else None
    fiber_target = round(FIBER_G_PER_1000_KCAL * target[1] / 1000) if target and target[1] else None

    nutrients = await _load_nutrients(db, [r[5] for r in rows])
    entries = []
    for d, ts, meal, cal, p, log_id in rows:
        known = nutrients.get(log_id) or {}
        entries.append(
            Entry(
                d, ts, meal, int(cal or 0), float(p or 0),
                sugar_g=_known(known, "sugar_g"),
                fiber_g=_known(known, "fiber_g"),
            )
        )
    return build_report(entries, today, protein_target, fiber_target, lang)


def _known(nutrients: dict, key: str) -> float | None:
    """A stored amount, or None when it is unknown (never zero)."""
    value = nutrients.get(key)
    return float(value) if isinstance(value, (int, float)) else None


async def _load_nutrients(db: AsyncSession, log_ids: list[str]) -> dict[str, dict]:
    """Sugar and fibre per entry. In a savepoint, and any failure (such as the
    migration not having been run) only means no sugar or fibre patterns."""
    if not log_ids:
        return {}
    try:
        async with db.begin_nested():
            found = (
                await db.execute(
                    select(FoodLogNutrients.log_id, FoodLogNutrients.nutrients).where(
                        FoodLogNutrients.log_id.in_(log_ids)
                    )
                )
            ).all()
        return {log_id: n for log_id, n in found if n}
    except Exception:  # noqa: BLE001
        log.warning("could not read food log nutrients for the weekly report", exc_info=True)
        return {}
