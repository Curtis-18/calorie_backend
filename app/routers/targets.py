import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user_id
from app.models.target import Target
from app.schemas.target import OnboardingIn, TargetOut
from app.services.target_calculator import (
    UnderageError,
    UnderweightLossError,
    calculate_targets,
    compute_targets,
)

log = logging.getLogger("calorie_backend")

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
    try:
        computed = calculate_targets(data)
    except UnderageError:
        raise HTTPException(
            status_code=422,
            detail="You need to be 18 or older to get calorie targets.",
        )
    except UnderweightLossError:
        raise HTTPException(
            status_code=422,
            detail=(
                "Your weight is already below the healthy range for your height, so we "
                "can't set a weight-loss target. Try \"Maintain\" or \"Gain\" instead."
            ),
        )

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

    return {
        **computed,
        "date_of_birth": data.date_of_birth,
        "sex": data.sex,
        "activity_level": data.activity_level,
        "goal": data.goal,
    }

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

    # Recompute from the stored answers so formula fixes reach existing users
    # on their next login, without them re-entering their profile. Persist
    # only when something actually changed.
    try:
        fresh = compute_targets(
            date_of_birth=target.date_of_birth,
            sex=target.sex,
            height_cm=target.height_cm,
            weight_kg=target.weight_kg,
            activity_level=target.activity_level,
            goal=target.goal,
        )
    except (UnderageError, UnderweightLossError):
        fresh = None  # an existing row the new rules refuse: leave it as it was
    except Exception:  # noqa: BLE001 - never fail a read over a recompute
        log.exception("target recompute failed; serving stored values")
        fresh = None

    if fresh is not None:
        changed = {
            k: fresh[k]
            for k in ("bmr", "tdee", "calorie_target", "protein_g", "fat_g", "carbs_g")
            if fresh[k] != getattr(target, k)
        }
        if changed:
            for k, v in changed.items():
                setattr(target, k, v)
            try:
                await db.commit()
            except Exception:  # noqa: BLE001 - serve the fresh numbers anyway
                await db.rollback()
                log.exception("failed to persist recomputed targets")

    bmi = target.weight_kg / ((target.height_cm / 100) ** 2)
    return {
        "date_of_birth": target.date_of_birth,
        "sex": target.sex,
        "activity_level": target.activity_level,
        "goal": target.goal,
        "height_cm": target.height_cm,
        "weight_kg": target.weight_kg,
        "bmr": fresh["bmr"] if fresh else target.bmr,
        "tdee": fresh["tdee"] if fresh else target.tdee,
        "calorie_target": fresh["calorie_target"] if fresh else target.calorie_target,
        "bmi": round(bmi, 1),
        "protein_g": fresh["protein_g"] if fresh else target.protein_g,
        "fat_g": fresh["fat_g"] if fresh else target.fat_g,
        "carbs_g": fresh["carbs_g"] if fresh else target.carbs_g,
    }
