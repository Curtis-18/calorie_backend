import uuid
from datetime import date as date_type, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dates import resolve_today
from app.core.security import get_current_user_id
from app.models.weight_log import WeightLog
from app.schemas.weight import WeightHistoryOut, WeightIn, WeightSavedOut
from app.services.weight_service import WeighIn, summarize, sync_targets_to_weight, with_trend

router = APIRouter(prefix="/weights", tags=["weights"])

EARLIEST = date_type(2000, 1, 1)


async def _history(db: AsyncSession, user_id: uuid.UUID, today: date_type) -> dict:
    rows = (
        await db.execute(
            select(WeightLog.log_date, WeightLog.weight_kg)
            .where(WeightLog.user_id == user_id, WeightLog.log_date <= today)
            .order_by(WeightLog.log_date)
        )
    ).all()
    points = with_trend([WeighIn(d, w) for d, w in rows])
    return {"entries": points, "summary": summarize(points, today)}


async def _latest(db: AsyncSession, user_id: uuid.UUID) -> tuple[date_type, float] | None:
    row = (
        await db.execute(
            select(WeightLog.log_date, WeightLog.weight_kg)
            .where(WeightLog.user_id == user_id)
            .order_by(WeightLog.log_date.desc())
            .limit(1)
        )
    ).first()
    return (row[0], row[1]) if row else None


@router.get("", response_model=WeightHistoryOut)
async def get_weights(
    date: date_type | None = None,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    return await _history(db, user_id, resolve_today(date))


@router.post("", response_model=WeightSavedOut)
async def log_weight(
    data: WeightIn,
    today: date_type | None = None,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Record a weigh-in (replacing any for that day) and, when it's the
    newest one, recompute the user's targets for the new weight."""
    current_day = resolve_today(today)
    day = data.date or current_day
    if day > current_day + timedelta(days=1) or day < EARLIEST:
        raise HTTPException(status_code=422, detail="That date isn't valid for a weigh-in.")

    await db.execute(
        pg_insert(WeightLog)
        .values(id=uuid.uuid4(), user_id=user_id, log_date=day, weight_kg=data.weight_kg)
        .on_conflict_do_update(
            constraint="weight_logs_user_day", set_={"weight_kg": data.weight_kg}
        )
    )

    targets_updated, notice = False, None
    latest = await _latest(db, user_id)
    if latest and latest[0] == day:
        targets_updated, notice = await sync_targets_to_weight(db, user_id, data.weight_kg)
    await db.commit()

    return {
        "history": await _history(db, user_id, current_day),
        "targets_updated": targets_updated,
        "notice": notice,
    }


@router.delete("/{log_date}", status_code=204)
async def delete_weight(
    log_date: date_type,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        delete(WeightLog).where(WeightLog.user_id == user_id, WeightLog.log_date == log_date)
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="No weigh-in on that day")
    # If the newest weigh-in was removed, targets follow the one before it.
    latest = await _latest(db, user_id)
    if latest:
        await sync_targets_to_weight(db, user_id, latest[1])
    await db.commit()
    return None
