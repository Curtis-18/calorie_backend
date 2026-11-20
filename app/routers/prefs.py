import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user_id
from app.models.user_prefs import UserPrefs
from app.services.regions import REGIONS, is_region

log = logging.getLogger("calorie_backend")

router = APIRouter(prefix="/prefs", tags=["prefs"])


class FoodPrefsIn(BaseModel):
    # A key from `regions`; null clears the choice.
    region: str | None = None


def _out(region: str | None) -> dict:
    return {"region": region, "regions": [{"key": k, "label": v} for k, v in REGIONS.items()]}


@router.get("/food")
async def get_food_prefs(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Where the person mostly eats (or null), and the choices to offer. Before
    the migration is run this simply answers "nothing chosen"."""
    try:
        async with db.begin_nested():
            row = (await db.execute(select(UserPrefs).where(UserPrefs.user_id == user_id))).scalar_one_or_none()
    except Exception:  # noqa: BLE001
        log.warning("user_prefs unavailable, answering with no region", exc_info=True)
        return _out(None)
    region = row.region if row is not None and is_region(row.region or "") else None
    return _out(region)


@router.post("/food")
async def set_food_prefs(
    data: FoodPrefsIn,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    if data.region is not None and not is_region(data.region):
        raise HTTPException(status_code=422, detail="Pick one of the listed regions.")
    try:
        async with db.begin_nested():
            await db.execute(
                pg_insert(UserPrefs)
                .values(user_id=user_id, region=data.region)
                .on_conflict_do_update(index_elements=["user_id"], set_={"region": data.region})
            )
        await db.commit()
    except Exception:  # noqa: BLE001
        await db.rollback()
        log.exception("could not save the region")
        raise HTTPException(status_code=503, detail="Couldn't save that right now. Try again in a little while.")
    return _out(data.region)
