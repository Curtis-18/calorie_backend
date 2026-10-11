import logging
import uuid
from datetime import date as date_type

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user_id
from app.models.food_log import FoodLog
from app.models.photo import DetectedFoodItem, PhotoAnalysisResponse
from app.schemas.food_log import FoodLogIn, FoodLogOut
from app.services.gemini_service import identify_foods
from app.services.usda_service import get_best_match

log = logging.getLogger("calorie_backend")

router = APIRouter(prefix="/logs", tags=["logs"])


@router.post("/analyze-photo", response_model=PhotoAnalysisResponse)
async def analyze_photo(
    photo: UploadFile,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    image_bytes = await photo.read()
    try:
        detected = await identify_foods(image_bytes, photo.content_type or "image/jpeg")
    except Exception:  # noqa: BLE001
        # An unhandled exception here returns a 500 without CORS headers, which
        # browsers surface as "Failed to fetch". Answer with a real 502 instead.
        log.exception("photo analysis failed")
        raise HTTPException(status_code=502, detail="Photo analysis is temporarily unavailable")

    def scale(per_100g: float | None, grams: float) -> float | None:
        return (per_100g / 100) * grams if per_100g is not None else None

    items = []
    for food in detected:
        match = await get_best_match(food["name"])
        grams = food["estimated_grams"]

        items.append(
            DetectedFoodItem(
                name=food["name"],
                estimated_grams=grams,
                calories_per_100g=match.calories_per_100g if match else None,
                estimated_calories=scale(match.calories_per_100g if match else None, grams),
                protein_g_per_100g=match.protein_g_per_100g if match else None,
                estimated_protein_g=scale(match.protein_g_per_100g if match else None, grams),
                carbs_g_per_100g=match.carbs_g_per_100g if match else None,
                estimated_carbs_g=scale(match.carbs_g_per_100g if match else None, grams),
                fat_g_per_100g=match.fat_g_per_100g if match else None,
                estimated_fat_g=scale(match.fat_g_per_100g if match else None, grams),
            )
        )

    return PhotoAnalysisResponse(items=items)


@router.post("", response_model=FoodLogOut, status_code=201)
async def create_log(
    data: FoodLogIn,
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
    except Exception:
        await db.rollback()
        # The id is client-generated, so a retry after a dropped response
        # lands on the primary key. Report it as a conflict, not a 500.
        raise HTTPException(status_code=409, detail="Log with this id already exists")
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
