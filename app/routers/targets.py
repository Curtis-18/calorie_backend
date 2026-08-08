import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user_id
from app.models.target import Target
from app.schemas.target import OnboardingIn, TargetOut
from app.services.target_calculator import calculate_targets

router = APIRouter(prefix="/targets", tags=["targets"])

@router.post("", response_model=TargetOut)
async def upsert_target(
    data: OnboardingIn,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Calculates and saves (or updates) the user's nutritional targets.
    """
    computed = calculate_targets(data)

    values = {
        "user_id": user_id,
        "date_of_birth": data.date_of_birth,
        "sex": data.sex,
        "height_cm": computed["height_cm"],
        "weight_kg": computed["weight_kg"],
        "activity_level": data.activity_level,
        "goal": data.goal,
        "bmr": computed["bmr"],
        "tdee": computed["tdee"],
        "calorie_target": computed["calorie_target"],
        "protein_g": computed["protein_g"],
        "fat_g": computed["fat_g"],
        "carbs_g": computed["carbs_g"],
    }

    # Use PostgreSQL UPSERT to ensure one record per user
    stmt = pg_insert(Target).values(**values).on_conflict_do_update(
        index_elements=["user_id"],
        set_={k: v for k, v in values.items() if k != "user_id"},
    )
    
    await db.execute(stmt)
    await db.commit()

    return computed

@router.get("", response_model=TargetOut)
async def get_target(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Retrieves the specific target for the logged-in user.
    """
    # FIXED: Using select().where() ensures we only ever fetch the row 
    # explicitly owned by this specific user_id.
    result = await db.execute(
        select(Target).where(Target.user_id == user_id)
    )
    target = result.scalar_one_or_none()

    if target is None:
        raise HTTPException(status_code=404, detail="No target set yet")

    # Calculate BMI on the fly for the dashboard
    bmi = target.weight_kg / ((target.height_cm / 100) ** 2)
    
    return {
        "height_cm": target.height_cm,
        "weight_kg": target.weight_kg,
        "bmr": target.bmr,
        "tdee": target.tdee,
        "calorie_target": target.calorie_target,
        "bmi": round(bmi, 1),
        "protein_g": target.protein_g,
        "fat_g": target.fat_g,
        "carbs_g": target.carbs_g,
    }
