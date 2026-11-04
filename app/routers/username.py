import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user_id
from app.models.user import Profile
from app.schemas.username import UsernameCheckOut, UsernameIn, UsernameOut
from app.services.username_service import can_change_at, validate_username

log = logging.getLogger("calorie_backend")

router = APIRouter(prefix="/username", tags=["username"])

TAKEN = "That username is taken."


async def _owner(db: AsyncSession, name: str) -> uuid.UUID | None:
    return (
        await db.execute(select(Profile.id).where(func.lower(Profile.username) == name.lower()))
    ).scalar_one_or_none()


@router.get("/check", response_model=UsernameCheckOut)
async def check_username(
    name: str = Query(..., max_length=64),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Live availability for the picker. Your own current name counts as free."""
    reason = validate_username(name)
    if reason:
        return {"available": False, "reason": reason}
    owner = await _owner(db, name.strip())
    if owner is not None and owner != user_id:
        return {"available": False, "reason": TAKEN}
    return {"available": True, "reason": None}


@router.post("", response_model=UsernameOut)
async def set_username(
    data: UsernameIn,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Pick a username (free the first time), or change it once per 30 days."""
    name = data.username.strip()
    reason = validate_username(name)
    if reason:
        raise HTTPException(status_code=422, detail=reason)

    row = (
        await db.execute(
            select(Profile.username, Profile.username_changed_at).where(Profile.id == user_id)
        )
    ).one()
    current, changed_at = row

    if current == name:  # nothing to do; a retried request lands here
        return {"username": current, "can_change_at": can_change_at(changed_at, True)}

    # Changing only the capitalisation of your own name is allowed freely.
    own_recase = current is not None and current.lower() == name.lower()
    if not own_recase:
        wait_until = can_change_at(changed_at, current is not None)
        if wait_until is not None:
            raise HTTPException(
                status_code=429,
                detail=f"You can change your username again on {wait_until:%d %b %Y}.",
            )
        owner = await _owner(db, name)
        if owner is not None and owner != user_id:
            raise HTTPException(status_code=409, detail=TAKEN)

    now = datetime.now(timezone.utc)
    try:
        await db.execute(
            update(Profile)
            .where(Profile.id == user_id)
            .values(
                username=name,
                username_changed_at=changed_at if own_recase else now,
            )
        )
        await db.commit()
    except IntegrityError:
        # Someone took it between our check and the write.
        await db.rollback()
        raise HTTPException(status_code=409, detail=TAKEN)
    return {"username": name, "can_change_at": can_change_at(None if own_recase else now, True)}
