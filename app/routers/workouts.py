"""The Workouts tab's library: curated routines, never model-written
(roadmap R9). Same fixed text the coach offers, written in the person's language."""

import uuid

from fastapi import APIRouter, Depends, HTTPException

from app.core.security import get_current_user_id
from app.core.language import get_language
from app.services import workouts

router = APIRouter(prefix="/workouts", tags=["workouts"])


@router.get("")
async def list_workouts(user_id: uuid.UUID = Depends(get_current_user_id), lang: str = Depends(get_language)):
    """Every routine as a card (id, name, minutes, focus, slice, level, summary), shortest first."""
    return workouts.library(lang)


@router.get("/{routine_id}")
async def get_workout(routine_id: str, user_id: uuid.UUID = Depends(get_current_user_id), lang: str = Depends(get_language)):
    """One routine: its sections for reading and a flat step list for the player."""
    routine = workouts.get(routine_id)
    if routine is None:
        raise HTTPException(404, "That workout isn't there any more.")
    return workouts.render(routine, lang)
