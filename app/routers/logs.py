import logging
import uuid
from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user_id
from app.models.food_log import FoodLog
from app.schemas.food_log import FoodLogIn, FoodLogOut

log = logging.getLogger("calorie_backend")

router = APIRouter(prefix="/logs", tags=["logs"])


@router.post("", response_model=FoodLogOut, status_code=201)
async def create_log(
    data: FoodLogIn,
    response: Response,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    entry = FoodLog(
        id=data.id,
        user_id=user_id,
        name=data.name,
        calories=data.calories,
        protein_g=data.protein_g,
        carbs_g=data.carbs_g,
        fat_g=data.fat_g,
        meal_type=data.meal_type,
        source=data.source,
        log_date=data.log_date,
        timestamp=data.timestamp,
    )
    db.add(entry)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        # The id is client-generated, so the usual cause is a retry after the
        # first response was lost (a Render cold start outlasting the client
        # timeout). That write already succeeded: answer 200 with the stored
        # row so the client treats it as saved instead of showing an error.
        result = await db.execute(select(FoodLog).where(FoodLog.id == data.id))
        existing = result.scalar_one_or_none()
        if existing is not None and existing.user_id == user_id:
            response.status_code = 200
            return existing
        if existing is not None:
            raise HTTPException(status_code=409, detail="Log with this id already exists")
        # Not a duplicate id, so some other constraint failed. Previously every
        # error here was reported as a 409 "already exists", which hid real
        # failures.
        log.exception("food log insert failed on a non-duplicate constraint")
        raise HTTPException(status_code=500, detail="Could not save this entry")
    except Exception:
        await db.rollback()
        # An HTTPException rather than a bare raise: an unhandled exception
        # becomes a 500 without CORS headers, which the web client can only
        # report as "Failed to fetch".
        log.exception("food log insert failed")
        raise HTTPException(status_code=500, detail="Could not save this entry")
    await db.refresh(entry)
    return entry


@router.get("/today", response_model=list[FoodLogOut])
async def get_today_logs(
    date: date_type,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(FoodLog).where(FoodLog.user_id == user_id, FoodLog.log_date == date)
    )
    return list(result.scalars().all())


@router.delete("/{log_id}", status_code=204)
async def delete_log(
    log_id: str,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    entry = await db.get(FoodLog, log_id)
    # get_current_user_id hands back a UUID. Comparing it against a str made
    # this condition unconditionally true, so every delete 404'd.
    if entry is None or entry.user_id != user_id:
        raise HTTPException(status_code=404, detail="Log not found")
    await db.delete(entry)
    await db.commit()
    return None
