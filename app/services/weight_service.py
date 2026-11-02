"""Weigh-in history, the smoothed trend, and keeping targets in step.

Day-to-day scale readings swing by a kilogram or more with water and food,
which hides real progress and discourages people. The trend line is an
exponential moving average (10% per day, as in Walker's "Hacker's Diet"),
weighted by the gap between weigh-ins so irregular logging still works.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.target import Target
from app.services.target_calculator import UnderageError, UnderweightLossError, compute_targets

TREND_DAILY_RETENTION = 0.9  # the trend keeps 90% of itself per day
MIN_WEIGHT_KG = 20
MAX_WEIGHT_KG = 400


@dataclass
class WeighIn:
    log_date: date
    weight_kg: float


def with_trend(weigh_ins: list[WeighIn]) -> list[dict]:
    """Weigh-ins oldest first, each with the smoothed trend at that point."""
    points: list[dict] = []
    trend: float | None = None
    previous: date | None = None
    for w in sorted(weigh_ins, key=lambda w: w.log_date):
        if trend is None:
            trend = w.weight_kg
        else:
            gap = max((w.log_date - previous).days, 1)
            alpha = 1 - TREND_DAILY_RETENTION**gap
            trend += alpha * (w.weight_kg - trend)
        previous = w.log_date
        points.append(
            {"date": w.log_date, "weight_kg": round(w.weight_kg, 2), "trend_kg": round(trend, 2)}
        )
    return points


def summarize(points: list[dict], today: date) -> dict | None:
    """Start, now and change. Change uses the trend, so one heavy morning
    doesn't erase a month of progress; the raw change is included too."""
    if not points:
        return None
    first, last = points[0], points[-1]
    return {
        "start_kg": first["weight_kg"],
        "start_date": first["date"],
        "current_kg": last["weight_kg"],
        "current_date": last["date"],
        "trend_kg": last["trend_kg"],
        "change_kg": round(last["trend_kg"] - first["weight_kg"], 1),
        "raw_change_kg": round(last["weight_kg"] - first["weight_kg"], 1),
        "lowest_kg": min(p["weight_kg"] for p in points),
        "highest_kg": max(p["weight_kg"] for p in points),
        "count": len(points),
        "days_since_last": (today - last["date"]).days,
    }


async def sync_targets_to_weight(
    db: AsyncSession, user_id, weight_kg: float
) -> tuple[bool, str | None]:
    """Recompute the user's targets for their newest weight.

    Targets come from body weight, so without this they stay pinned to the
    onboarding weight and drift too high as someone loses. Returns whether
    targets changed and an optional notice for the user. Commits nothing:
    the caller owns the transaction.
    """
    target = (
        await db.execute(select(Target).where(Target.user_id == user_id))
    ).scalar_one_or_none()
    if target is None:
        return False, None

    notice = None
    goal = target.goal
    try:
        fresh = compute_targets(
            date_of_birth=target.date_of_birth, sex=target.sex, height_cm=target.height_cm,
            weight_kg=weight_kg, activity_level=target.activity_level, goal=goal,
        )
    except UnderweightLossError:
        # They've reached the bottom of the healthy range: stop the deficit.
        goal = "maintain"
        fresh = compute_targets(
            date_of_birth=target.date_of_birth, sex=target.sex, height_cm=target.height_cm,
            weight_kg=weight_kg, activity_level=target.activity_level, goal=goal,
        )
        notice = (
            "You've reached the lower end of the healthy weight range for your height, "
            "so we've switched your goal to Maintain."
        )
    except UnderageError:
        return False, None

    target.weight_kg = fresh["weight_kg"]
    target.goal = goal
    for key in ("bmr", "tdee", "calorie_target", "protein_g", "fat_g", "carbs_g"):
        setattr(target, key, fresh[key])
    return True, notice
