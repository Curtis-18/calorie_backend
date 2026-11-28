"""Movement logs and the week (roadmap R9). Private to the person."""

import logging
import uuid
from datetime import date as date_type, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dates import resolve_today
from app.core.language import get_language
from app.core.security import get_current_user_id
from app.models.movement import MovementLog, MovementPrefs
from app.models.weight_log import WeightLog
from app.schemas.movement import MovementIn, MovementOut, WeekOut
from app.services import movement, movement_read, movement_sets, workouts

log = logging.getLogger("calorie_backend")

router = APIRouter(prefix="/movement", tags=["movement"])

LIST_DAYS = 60
LIST_LIMIT = 100


def _out(row, lang: str) -> dict:
    return {
        "id": row.id, "date": row.log_date, "activity": row.activity, "label": movement.label_for(row.activity, lang),
        "slice": row.slice, "minutes": row.minutes, "intensity": row.intensity, "routine_id": row.routine_id,
        "source": row.source, "est_kcal": row.est_kcal, "created_at": getattr(row, "created_at", None),
    }


async def _latest_weight(db: AsyncSession, user_id: uuid.UUID) -> float | None:
    """The most recent weigh-in, for the rough estimate. Own savepoint, never raises."""
    try:
        async with db.begin_nested():
            value = (
                await db.execute(
                    select(WeightLog.weight_kg).where(WeightLog.user_id == user_id).order_by(WeightLog.log_date.desc()).limit(1)
                )
            ).scalar_one_or_none()
        return float(value) if value else None
    except Exception:  # noqa: BLE001 - the estimate is a nicety
        log.warning("movement: could not read the weight", exc_info=True)
        return None


def _decide(data: MovementIn) -> tuple[str, str, str, str | None, str]:
    """(activity, slice, intensity, routine_id, source) from what was sent, or a 422."""
    if data.routine_id:
        routine = workouts.get(data.routine_id)
        if routine is None:
            raise HTTPException(422, "That workout isn't there any more.")
        return (
            movement.session_activity(routine), workouts.slice_of(routine),
            data.intensity or movement.session_intensity(routine), routine.id, "session",
        )
    if data.activity not in movement.manual_choices():
        raise HTTPException(422, "Pick one of the activities in the list.")
    return data.activity, movement.slice_for(data.activity), data.intensity or "moderate", None, "manual"


@router.post("", response_model=MovementOut)
async def log_movement(
    data: MovementIn,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
    lang: str = Depends(get_language),
):
    """Log some movement. Repeating the same request (same id) is harmless."""
    existing = (await db.execute(select(MovementLog).where(MovementLog.id == data.id))).scalar_one_or_none()
    if existing is not None:
        if existing.user_id != user_id:
            raise HTTPException(409, "That id is already used.")
        return _out(existing, lang)

    activity, slice_, intensity, routine_id, source = _decide(data)
    day = resolve_today(data.date)
    weight = await _latest_weight(db, user_id)
    row = {
        "id": data.id, "user_id": user_id, "log_date": day, "slice": slice_, "activity": activity,
        "minutes": data.minutes, "intensity": intensity, "routine_id": routine_id, "source": source,
        "est_kcal": movement.estimate_kcal(activity, intensity, data.minutes, weight),
    }
    sets = movement_sets.clean_sets(data.sets) if source == "session" else []
    try:
        inserted = await db.execute(pg_insert(MovementLog).values(row).on_conflict_do_nothing().returning(MovementLog.id))
        # Only with the session that was just written (never twice for a retry
        # that raced the first attempt), and in a savepoint: no table, no sets.
        if sets and inserted.scalar_one_or_none() is not None:
            await movement_sets.save(db, user_id, data.id, sets)
        await db.commit()
    except Exception:  # noqa: BLE001
        await db.rollback()
        log.exception("saving movement failed")
        raise HTTPException(500, "Couldn't save that. Please try again.")
    return _out(type("Row", (), {**row, "created_at": datetime.now(timezone.utc)}), lang)


@router.get("", response_model=list[MovementOut])
async def list_movement(
    date: date_type | None = None,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
    lang: str = Depends(get_language),
):
    """The latest things you did, newest first. A missing table reads as an empty list."""
    since = resolve_today(date) - timedelta(days=LIST_DAYS)
    try:
        async with db.begin_nested():
            rows = (
                await db.execute(
                    select(MovementLog)
                    .where(MovementLog.user_id == user_id, MovementLog.log_date >= since)
                    .order_by(MovementLog.log_date.desc(), MovementLog.created_at.desc())
                    .limit(LIST_LIMIT)
                )
            ).scalars().all()
    except Exception:  # noqa: BLE001
        log.warning("movement: could not read the list", exc_info=True)
        return []
    return [_out(r, lang) for r in rows]


@router.get("/week", response_model=WeekOut)
async def this_week(
    date: date_type | None = None,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """This week (Monday to Sunday): minutes, the four slices, rest days and the
    run of "moved weeks". Reads about a year back for the run."""
    today = resolve_today(date)
    since = movement.week_start(today) - timedelta(weeks=movement.MAX_WEEKS_BACK)
    try:
        async with db.begin_nested():
            result = await db.execute(
                select(MovementLog.log_date, MovementLog.slice, MovementLog.minutes).where(
                    MovementLog.user_id == user_id, MovementLog.log_date >= since, MovementLog.log_date <= today
                )
            )
            rows = [(d, s, int(m)) for d, s, m in result.all()]
    except Exception:  # noqa: BLE001 - table missing (migration not run): an empty week
        log.warning("movement: could not read the week", exc_info=True)
        rows = []
    week = movement.summarise_week(rows, today)
    week["streak"] = movement.moved_weeks(rows, today)
    week["eat_back_percent"], week["eat_back_kcal"] = await movement_read.today_eat_back(db, user_id, today)
    return week


@router.delete("/{movement_id}", status_code=204)
async def delete_movement(
    movement_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    gone = await db.execute(delete(MovementLog).where(MovementLog.id == movement_id, MovementLog.user_id == user_id))
    if not gone.rowcount:
        raise HTTPException(404, "That isn't there any more.")
    await db.commit()
    return None


@router.get("/choices")
async def choices(user_id: uuid.UUID = Depends(get_current_user_id), lang: str = Depends(get_language)):
    """The activities that can be logged by hand, each with its slice."""
    return {
        "activities": [
            {"key": k, "label": movement.label_for(k, lang), "slice": movement.slice_for(k)} for k in movement.manual_choices()
        ],
        "intensities": list(movement.INTENSITIES),
    }


class PrefsIn(BaseModel):
    eat_back_percent: int = Field(..., ge=0, le=movement.EAT_BACK_MAX_PERCENT)


@router.get("/prefs")
async def get_prefs(user_id: uuid.UUID = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    """Whether movement is added to the calorie plan, and how much (0 = off, the default)."""
    return {"eat_back_percent": await movement_read.eat_back_percent(db, user_id), "max_percent": movement.EAT_BACK_MAX_PERCENT,
            "daily_cap_kcal": movement.EAT_BACK_DAILY_CAP_KCAL}


@router.post("/prefs")
async def set_prefs(data: PrefsIn, user_id: uuid.UUID = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    """Choose how much of your logged movement is added to today's plan. POST, like the other choices."""
    try:
        async with db.begin_nested():
            await db.execute(
                pg_insert(MovementPrefs)
                .values(user_id=user_id, eat_back_percent=data.eat_back_percent)
                .on_conflict_do_update(
                    index_elements=[MovementPrefs.user_id], set_={"eat_back_percent": data.eat_back_percent, "updated_at": func.now()}
                )
            )
        await db.commit()
    except Exception:  # noqa: BLE001
        await db.rollback()
        log.exception("movement prefs not saved")
        raise HTTPException(503, "Couldn't save that right now")
    return {"eat_back_percent": data.eat_back_percent, "max_percent": movement.EAT_BACK_MAX_PERCENT,
            "daily_cap_kcal": movement.EAT_BACK_DAILY_CAP_KCAL}
