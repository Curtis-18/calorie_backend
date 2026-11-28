"""Reps per move in guided workouts, for "Last time: 12" in the player
(NEXT_STEPS step 9b). Private to the person.

Everything here runs in a savepoint and never raises: until the owner runs
migrations/2026-11-29_movement_sets.sql the table is missing, and a workout
must still save and open exactly as before (just without "Last time").
"""

import logging
import uuid

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.movement import MovementSet
from app.services import workouts

log = logging.getLogger("calorie_backend")

# How many recent rows to look through for "last time" (a long session has
# about 30 rep sets, so this covers several sessions).
RECENT_ROWS = 300


def clean_sets(sets) -> list[tuple[str, int]]:
    """(move, reps) pairs the server can store: moves from the library only
    (anything else is dropped, never refused, so the session itself still
    saves), reps already bounded by the request model."""
    return [(s.move, s.reps) for s in sets or () if s.move in workouts.EXERCISES]


async def save(db: AsyncSession, user_id: uuid.UUID, log_id: uuid.UUID, sets: list[tuple[str, int]]) -> bool:
    """Store the session's sets. False (and logged) when the table is missing."""
    if not sets:
        return True
    try:
        async with db.begin_nested():
            await db.execute(
                insert(MovementSet).values(
                    [{"id": uuid.uuid4(), "user_id": user_id, "log_id": log_id, "move": move, "reps": reps} for move, reps in sets]
                )
            )
        return True
    except Exception:  # noqa: BLE001 - table missing (migration not run): the session still saves
        log.warning("movement_sets: could not save", exc_info=True)
        return False


def latest_by_move(rows) -> dict[str, int]:
    """[rows]: (move, reps, log_id), newest first. For each move, the most reps
    in one set in the most recent session that had it."""
    session_of: dict[str, object] = {}
    best: dict[str, int] = {}
    for move, reps, log_id in rows:
        if move not in session_of:
            session_of[move] = log_id
        if session_of[move] == log_id:
            best[move] = max(best.get(move, 0), int(reps))
    return best


async def last_reps(db: AsyncSession, user_id: uuid.UUID, moves: set[str]) -> dict[str, int]:
    """{move: reps last time} for [moves]; empty when there is nothing yet or the table is missing."""
    if not moves:
        return {}
    try:
        async with db.begin_nested():
            rows = (
                await db.execute(
                    select(MovementSet.move, MovementSet.reps, MovementSet.log_id)
                    .where(MovementSet.user_id == user_id, MovementSet.move.in_(sorted(moves)))
                    .order_by(MovementSet.created_at.desc(), MovementSet.id)
                    .limit(RECENT_ROWS)
                )
            ).all()
    except Exception:  # noqa: BLE001 - table missing: no "Last time" yet
        log.warning("movement_sets: could not read", exc_info=True)
        return {}
    return latest_by_move(rows)
