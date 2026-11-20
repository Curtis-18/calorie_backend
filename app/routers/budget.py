import logging
import uuid
from datetime import date as date_type
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dates import resolve_today
from app.core.language import get_language
from app.core.security import get_current_user_id
from app.i18n import t
from app.models.budget_prefs import BudgetPrefs
from app.models.food_log import FoodLog
from app.models.target import Target
from app.services.target_calculator import MIN_CALORIES
from app.services.week_budget import (
    DAYS, compute_nudge, compute_week_budget, valid_weights, week_start_of,
)

log = logging.getLogger("calorie_backend")

router = APIRouter(prefix="/budget", tags=["budget"])

_KEEP_WEEKS = 12


class PrefsIn(BaseModel):
    """Any subset. Omitted fields are left alone."""

    mode: Literal["daily", "weekly"] | None = None
    week_start_day: int | None = Field(None, ge=0, le=6)
    # Seven numbers adding to 7 ("weekend flex"); an empty list clears it.
    weights: list[float] | None = Field(None, max_length=DAYS)
    nudges: bool | None = None
    # Decline the spread-it card for the week that starts on this date.
    dismiss_week: date_type | None = None


def _defaults() -> dict:
    return {"mode": "daily", "week_start_day": 0, "weights": None, "nudges": False, "dismissed_weeks": []}


async def _load_prefs(db: AsyncSession, user_id: uuid.UUID) -> dict:
    """The person's choices, or the defaults when there are none or the table
    does not exist yet (before the migration)."""
    try:
        async with db.begin_nested():
            row = (await db.execute(select(BudgetPrefs).where(BudgetPrefs.user_id == user_id))).scalar_one_or_none()
    except Exception:  # noqa: BLE001
        log.warning("budget_prefs unavailable, using defaults", exc_info=True)
        return _defaults()
    if row is None:
        return _defaults()
    return {
        "mode": row.mode,
        "week_start_day": row.week_start_day,
        "weights": row.weights,
        "nudges": row.nudges,
        "dismissed_weeks": list(row.dismissed_weeks or []),
    }


async def _target(db: AsyncSession, user_id: uuid.UUID) -> Target:
    target = (await db.execute(select(Target).where(Target.user_id == user_id))).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="Finish setting up your plan first")
    return target


@router.get("/prefs")
async def get_prefs(user_id: uuid.UUID = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    return await _load_prefs(db, user_id)


@router.post("/prefs")
async def update_prefs(
    data: PrefsIn,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Change any weekly-budget choice. POST rather than PATCH, like the
    notification choices, so the CORS method list stays as it is."""
    current = await _load_prefs(db, user_id)
    values: dict = {}
    if data.mode is not None:
        values["mode"] = data.mode
    if data.week_start_day is not None:
        values["week_start_day"] = data.week_start_day
    if data.nudges is not None:
        values["nudges"] = data.nudges
    if "weights" in data.model_fields_set:
        if not data.weights:
            values["weights"] = None
        else:
            target = await _target(db, user_id)
            floor = MIN_CALORIES[target.sex]
            if not valid_weights(data.weights, target.calorie_target, floor):
                raise HTTPException(
                    status_code=422,
                    detail="Those weekday amounts don't add up. Keep every day within 15% of normal, and the week at seven days' worth.",
                )
            values["weights"] = [float(w) for w in data.weights]
    if data.dismiss_week is not None:
        weeks = [w for w in current["dismissed_weeks"] if w != data.dismiss_week.isoformat()]
        weeks.append(data.dismiss_week.isoformat())
        values["dismissed_weeks"] = weeks[-_KEEP_WEEKS:]
    if not values:
        return current

    try:
        async with db.begin_nested():
            await db.execute(
                pg_insert(BudgetPrefs)
                .values(user_id=user_id, **values)
                .on_conflict_do_update(index_elements=[BudgetPrefs.user_id], set_={**values, "updated_at": func.now()})
            )
        await db.commit()
    except Exception:  # noqa: BLE001
        log.exception("budget prefs not saved")
        raise HTTPException(status_code=503, detail="Couldn't save that right now")
    return await _load_prefs(db, user_id)


@router.get("/week")
async def get_week(
    date: date_type | None = None,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
    lang: str = Depends(get_language),
):
    """This week's allowance, derived from the logs (nothing is stored).

    `date` is the device-local today, as everywhere else.
    """
    today = resolve_today(date)
    target = await _target(db, user_id)
    prefs = await _load_prefs(db, user_id)
    floor = MIN_CALORIES[target.sex]

    start = week_start_of(today, prefs["week_start_day"])
    rows = (
        await db.execute(
            select(FoodLog.log_date, func.sum(FoodLog.calories))
            .where(FoodLog.user_id == user_id, FoodLog.log_date >= start, FoodLog.log_date <= today)
            .group_by(FoodLog.log_date)
        )
    ).all()
    eaten = {d: int(total or 0) for d, total in rows}

    week = compute_week_budget(
        today=today,
        target=target.calorie_target,
        floor=floor,
        eaten_by_date=eaten,
        start_day=prefs["week_start_day"],
        weights=prefs["weights"],
    )

    weekly = prefs["mode"] == "weekly"
    shown = week.today.allowance if weekly else week.today.base
    days_left_after = (week.days[-1].day - today).days

    nudge = None
    if prefs["nudges"] and week.week_start.isoformat() not in prefs["dismissed_weeks"]:
        found = compute_nudge(
            shown_allowance=shown,
            eaten_today=eaten.get(today, 0),
            days_left_after_today=days_left_after,
            target=target.calorie_target,
            floor=floor,
            goal=target.goal,
            lang=lang,
        )
        if found is not None:
            nudge = {
                "kind": found.kind, "over_by": found.over_by, "days": found.days,
                "per_day": found.per_day, "message": found.message,
            }

    return {
        "mode": prefs["mode"],
        "nudges": prefs["nudges"],
        "week_start": week.week_start,
        "daily_target": target.calorie_target,
        "floor": floor,
        "allowance_today": shown,
        "bank": week.bank,
        "explanation": _explain(week.bank, weekly, lang),
        "days": [
            {"date": d.day, "base": d.base, "eaten": d.eaten, "state": d.state, "allowance": d.allowance}
            for d in week.days
        ],
        "nudge": nudge,
    }


def _explain(bank: int, weekly: bool, lang: str = "en") -> str:
    if not weekly:
        return t(lang, "Your target is the same every day.")
    if abs(bank) < 25:
        return t(lang, "You're right on plan this week, so today's target is your usual one.")
    if bank < 0:
        return t(
            lang,
            "A recent day had a bit extra, so today's plan is a little lower. "
            "It's spread over the rest of the week so no single day takes it all.",
        )
    return t(lang, "A recent day had a bit left over, so today's plan has a little extra room.")
