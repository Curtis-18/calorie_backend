from datetime import date as date_type

from fastapi import APIRouter, UploadFile, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.photo import DetectedFoodItem, PhotoAnalysisResponse
from app.models.food_log import FoodLog
from app.schemas.food_log import FoodLogIn, FoodLogOut
from app.services.gemini_service import identify_foods
from app.services.usda_service import get_best_match
from app.core.security import get_current_user_id
from app.core.database import get_db

router = APIRouter(prefix="/logs", tags=["logs"])

@router.post("/analyze-photo", response_model=PhotoAnalysisResponse)
async def analyze_photo(photo: UploadFile, user_id: str = Depends(get_current_user_id)):
    image_bytes = await photo.read()
    detected = await identify_foods(image_bytes, photo.content_type)

    def scale(per_100g: float | None, grams: float) -> float | None:
        return (per_100g / 100) * grams if per_100g is not None else None

    items = []
    for food in detected:
        match = await get_best_match(food["name"])
        grams = food["estimated_grams"]

        calories_per_100g = match.calories_per_100g if match else None
        protein_per_100g = match.protein_g_per_100g if match else None
        carbs_per_100g = match.carbs_g_per_100g if match else None
        fat_per_100g = match.fat_g_per_100g if match else None

        items.append(
            DetectedFoodItem(
                name=food["name"],
                estimated_grams=grams,
                calories_per_100g=calories_per_100g,
                estimated_calories=scale(calories_per_100g, grams),
                protein_g_per_100g=protein_per_100g,
                estimated_protein_g=scale(protein_per_100g, grams),
                carbs_g_per_100g=carbs_per_100g,
                estimated_carbs_g=scale(carbs_per_100g, grams),
                fat_g_per_100g=fat_per_100g,
                estimated_fat_g=scale(fat_per_100g, grams),
            )
        )

    return PhotoAnalysisResponse(items=items)
@router.post("", response_model=FoodLogOut, status_code=201)
async def create_log(
    data: FoodLogIn,
    user_id: str = Depends(get_current_user_id),
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
    await db.commit()
    await db.refresh(entry)
    return entry

@router.get("/today", response_model=list[FoodLogOut])
async def get_today_logs(
    date: date_type,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(FoodLog).where(FoodLog.user_id == user_id, FoodLog.log_date == date)
    )
    return result.scalars().all()


@router.delete("/{log_id}", status_code=204)
async def delete_log(
    log_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    entry = await db.get(FoodLog, log_id)
    if entry is None or str(entry.user_id) != user_id:
        raise HTTPException(status_code=404, detail="Log not found")
    await db.delete(entry)
    await db.commit()