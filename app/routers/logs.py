import logging
import uuid
from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user_id
from app.models.food_log import FoodLog
from app.models.food_log_nutrients import FoodLogNutrients
from app.schemas.food_log import FoodLogIn, FoodLogOut, FoodLogUpdate

log = logging.getLogger("calorie_backend")

router = APIRouter(prefix="/logs", tags=["logs"])


# Nutrients live in their own table (see FoodLogNutrients). Every touch of it
# sits in a savepoint and swallows errors: if the migration hasn't been run, or
# the write fails, the food log itself must still save and load.

async def _load_nutrients(db: AsyncSession, log_ids: list[str]) -> dict[str, dict]:
    if not log_ids:
        return {}
    try:
        async with db.begin_nested():
            rows = (
                await db.execute(
                    select(FoodLogNutrients.log_id, FoodLogNutrients.nutrients).where(
                        FoodLogNutrients.log_id.in_(log_ids)
                    )
                )
            ).all()
        return {log_id: nutrients for log_id, nutrients in rows if nutrients}
    except Exception:  # noqa: BLE001
        log.warning("could not read food log nutrients", exc_info=True)
        return {}


async def _write_nutrients(db: AsyncSession, log_id: str, known: dict[str, float] | None) -> None:
    """Store the known amounts for an entry, or remove them when there are
    none. Commits nothing: the caller owns the transaction."""
    try:
        async with db.begin_nested():
            if known:
                await db.execute(
                    pg_insert(FoodLogNutrients)
                    .values(log_id=log_id, nutrients=known)
                    .on_conflict_do_update(index_elements=["log_id"], set_={"nutrients": known})
                )
            else:
                await db.execute(delete(FoodLogNutrients).where(FoodLogNutrients.log_id == log_id))
    except Exception:  # noqa: BLE001
        log.warning("could not save food log nutrients", exc_info=True)


def _out(entry: FoodLog, nutrients: dict | None) -> dict:
    return {
        "id": entry.id,
        "name": entry.name,
        "calories": entry.calories,
        "protein_g": entry.protein_g,
        "carbs_g": entry.carbs_g,
        "fat_g": entry.fat_g,
        "meal_type": entry.meal_type,
        "source": entry.source,
        "timestamp": entry.timestamp,
        "log_date": entry.log_date,
        "nutrients": nutrients or None,
    }


async def _store_new_nutrients(db: AsyncSession, data: FoodLogIn) -> dict | None:
    """After the entry itself is safely saved. Returns what is now stored."""
    known = data.nutrients.known() if data.nutrients else None
    if not known:
        return None
    await _write_nutrients(db, data.id, known)
    try:
        await db.commit()
    except Exception:  # noqa: BLE001
        await db.rollback()
        log.warning("could not commit food log nutrients", exc_info=True)
        return None
    return known


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
            # The first attempt may have saved the entry but not its nutrients.
            return _out(existing, await _store_new_nutrients(db, data))
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
    return _out(entry, await _store_new_nutrients(db, data))


@router.get("/today", response_model=list[FoodLogOut])
async def get_today_logs(
    date: date_type,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(FoodLog).where(FoodLog.user_id == user_id, FoodLog.log_date == date)
    )
    entries = list(result.scalars().all())
    nutrients = await _load_nutrients(db, [e.id for e in entries])
    return [_out(e, nutrients.get(e.id)) for e in entries]


@router.patch("/{log_id}", response_model=FoodLogOut)
async def update_log(
    log_id: str,
    data: FoodLogUpdate,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Correct a saved entry (a wrong portion, food or meal). The values sent
    replace the stored ones, so repeating the request after a lost response is
    harmless."""
    entry = await db.get(FoodLog, log_id)
    if entry is None or entry.user_id != user_id:
        raise HTTPException(status_code=404, detail="Log not found")

    # A field sent as null means "not changing it", the same as leaving it out.
    changes = {
        k: v for k, v in data.model_dump(exclude_unset=True, exclude={"nutrients"}).items() if v is not None
    }
    if "name" in changes:
        changes["name"] = changes["name"].strip()
        if not changes["name"]:
            raise HTTPException(status_code=422, detail="The name can't be empty.")
    for field, value in changes.items():
        setattr(entry, field, value)
    if "nutrients" in data.model_fields_set:
        await _write_nutrients(db, log_id, data.nutrients.known() if data.nutrients else None)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        # An HTTPException keeps the CORS headers, so the web app sees a real
        # error instead of "Failed to fetch".
        log.exception("food log update failed")
        raise HTTPException(status_code=500, detail="Could not save this change")
    return _out(entry, (await _load_nutrients(db, [log_id])).get(log_id))


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
