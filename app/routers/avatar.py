"""Profile pictures: set, replace and remove your own."""

import logging
import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user_id
from app.models.story import ProfileAvatar
from app.schemas.stories import AvatarIn, AvatarOut
from app.services import avatars, storage_service
from app.services.images import decode_photo
from app.services.storage_service import StorageUnavailable

log = logging.getLogger("calorie_backend")

router = APIRouter(prefix="/me/avatar", tags=["avatar"])

NOT_SET_UP = "Profile photos aren't available right now. Please try again later."


async def _remove_file(path: str | None) -> None:
    """Best effort: a leftover file is invisible (nothing links to it) and
    account deletion clears it, so it must never fail the request."""
    if not path:
        return
    try:
        await storage_service.delete([path])
    except StorageUnavailable:
        log.warning("could not delete old profile picture %s", path)


@router.post("", response_model=AvatarOut)
async def set_avatar(
    data: AvatarIn,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Set or replace your profile picture."""
    if not storage_service.configured():
        raise HTTPException(503, NOT_SET_UP)
    image, mime, ext = decode_photo(data.image, settings.max_avatar_bytes)

    try:
        old = (
            await db.execute(select(ProfileAvatar.storage_path).where(ProfileAvatar.user_id == user_id))
        ).scalar_one_or_none()
    except Exception:  # noqa: BLE001 - the table isn't there until the migration is run
        await db.rollback()
        log.exception("could not read profile picture")
        raise HTTPException(503, NOT_SET_UP)

    # A new name every time, so a link to the old picture can never show the new one.
    path = f"{user_id}/avatar-{secrets.token_hex(8)}.{ext}"
    try:
        await storage_service.upload(path, image, mime)
    except StorageUnavailable:
        log.exception("profile picture upload failed")
        raise HTTPException(502, "Couldn't upload that photo. Please try again.")

    try:
        await db.execute(
            pg_insert(ProfileAvatar)
            .values(user_id=user_id, storage_path=path)
            .on_conflict_do_update(
                index_elements=[ProfileAvatar.user_id],
                set_={"storage_path": path, "updated_at": func.now()},
            )
        )
        await db.commit()
    except Exception:  # noqa: BLE001
        await db.rollback()
        log.exception("saving profile picture failed")
        await _remove_file(path)
        raise HTTPException(500, "Couldn't save your photo. Please try again.")

    if old and old != path:
        await _remove_file(old)
    return {"avatar_url": (await avatars.links_for([path])).get(path)}


@router.delete("", status_code=204)
async def remove_avatar(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Go back to the coloured initial. Harmless if there is no picture."""
    try:
        old = (
            await db.execute(select(ProfileAvatar.storage_path).where(ProfileAvatar.user_id == user_id))
        ).scalar_one_or_none()
        if old:
            await db.execute(delete(ProfileAvatar).where(ProfileAvatar.user_id == user_id))
            await db.commit()
    except Exception:  # noqa: BLE001
        await db.rollback()
        log.exception("removing profile picture failed")
        raise HTTPException(503, NOT_SET_UP)
    if old and storage_service.configured():
        await _remove_file(old)
    return None
