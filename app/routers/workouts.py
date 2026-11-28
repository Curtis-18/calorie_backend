"""The Workouts tab's library: curated routines, never model-written
(roadmap R9). Same fixed text the coach offers, written in the person's language."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user_id
from app.core.language import get_language
from app.services import movement_sets, workouts

router = APIRouter(prefix="/workouts", tags=["workouts"])


@router.get("")
async def list_workouts(user_id: uuid.UUID = Depends(get_current_user_id), lang: str = Depends(get_language)):
    """Every routine as a card (id, name, minutes, focus, slice, level, summary), shortest first."""
    return workouts.library(lang)


@router.get("/{routine_id}")
async def get_workout(
    routine_id: str,
    user_id: uuid.UUID = Depends(get_current_user_id),
    lang: str = Depends(get_language),
    db: AsyncSession = Depends(get_db),
):
    """One routine: its sections for reading, a flat step list for the player,
    and `last_reps` ({move id: reps}) from the last time each of its rep moves
    was done (empty until there is history, or before the migration)."""
    routine = workouts.get(routine_id)
    if routine is None:
        raise HTTPException(404, "That workout isn't there any more.")
    body = workouts.render(routine, lang)
    moves = set()
    for step in body["play"]:
        if step["mode"] == "reps":
            moves.add(step["move"])
        if step.get("easier") and step["easier"]["mode"] == "reps":
            moves.add(step["easier"]["move"])
    body["last_reps"] = await movement_sets.last_reps(db, user_id, moves)
    return body
