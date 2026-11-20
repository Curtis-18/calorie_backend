"""Recipe photos: a cover and up to five carousel slides, plus reporting a recipe.

Photos are re-encoded as plain JPEGs (no location data) and kept in the
private bucket; people only ever get short-lived signed links, and only for
recipes they are allowed to open.
"""

import logging
import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, Path, Response
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user_id
from app.models.recipe import RecipeMedia
from app.models.story import ContentReport
from app.routers.recipes import _mine, readable
from app.schemas.recipes import MediaIn
from app.schemas.snaps import ReportIn
from app.services import recipe_photos, storage_service
from app.services.images import clean_photo, decode_photo
from app.services.storage_service import StorageUnavailable

log = logging.getLogger("calorie_backend")

router = APIRouter(prefix="/recipes", tags=["recipe photos"])

NOT_SET_UP = "Recipe photos aren't available right now. Please try again later."


async def _remove_file(path: str | None) -> None:
    """Best effort: a file nothing links to is invisible, and account deletion
    clears it, so a failure here must never fail the request."""
    if not path:
        return
    try:
        await storage_service.delete([path])
    except StorageUnavailable:
        log.warning("could not delete recipe photo %s", path)


@router.get("/{recipe_id}/media")
async def list_media(recipe_id: uuid.UUID, user_id: uuid.UUID = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    recipe = await readable(db, user_id, recipe_id)
    return await recipe_photos.media(db, recipe.id)


@router.put("/{recipe_id}/media/{position}")
async def put_media(
    recipe_id: uuid.UUID,
    data: MediaIn,
    position: int = Path(ge=0, le=recipe_photos.MAX_SLIDES),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Add or replace the cover (position 0) or a slide (1-5). Replacing gives
    the photo a new file name, so an old link can never show the new photo."""
    if not storage_service.configured():
        raise HTTPException(503, NOT_SET_UP)
    recipe = await _mine(db, user_id, recipe_id)
    image, _, _ = decode_photo(data.image, settings.max_recipe_photo_bytes)
    image, mime, ext = await clean_photo(image)

    try:
        old = (
            await db.execute(
                select(RecipeMedia.path).where(RecipeMedia.recipe_id == recipe.id, RecipeMedia.position == position)
            )
        ).scalar_one_or_none()
    except Exception:  # noqa: BLE001 - the table isn't there until the migration is run
        await db.rollback()
        log.exception("could not read recipe photos")
        raise HTTPException(503, NOT_SET_UP)

    path = f"{user_id}/recipe-{recipe.id}-{position}-{secrets.token_hex(6)}.{ext}"
    try:
        await storage_service.upload(path, image, mime)
    except StorageUnavailable:
        log.exception("recipe photo upload failed")
        raise HTTPException(502, "Couldn't upload that photo. Please try again.")
    try:
        await db.execute(
            pg_insert(RecipeMedia)
            .values(recipe_id=recipe.id, position=position, path=path, caption=data.caption)
            .on_conflict_do_update(
                index_elements=[RecipeMedia.recipe_id, RecipeMedia.position],
                set_={"path": path, "caption": data.caption},
            )
        )
        await db.commit()
    except Exception:  # noqa: BLE001
        await db.rollback()
        log.exception("saving recipe photo failed")
        await _remove_file(path)
        raise HTTPException(500, "Couldn't save that photo. Please try again.")
    if old and old != path:
        await _remove_file(old)
    links = await recipe_photos.signed_links([path])
    return {"position": position, "caption": data.caption, "url": links.get(path)}


@router.delete("/{recipe_id}/media/{position}", status_code=204)
async def delete_media(
    recipe_id: uuid.UUID,
    position: int = Path(ge=0, le=recipe_photos.MAX_SLIDES),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Harmless if there is no photo there."""
    recipe = await _mine(db, user_id, recipe_id)
    try:
        old = (
            await db.execute(
                select(RecipeMedia.path).where(RecipeMedia.recipe_id == recipe.id, RecipeMedia.position == position)
            )
        ).scalar_one_or_none()
        if old:
            await db.execute(delete(RecipeMedia).where(RecipeMedia.recipe_id == recipe.id, RecipeMedia.position == position))
            await db.commit()
    except Exception:  # noqa: BLE001
        await db.rollback()
        log.exception("removing recipe photo failed")
        raise HTTPException(503, NOT_SET_UP)
    if old and storage_service.configured():
        await _remove_file(old)
    return Response(status_code=204)


@router.post("/{recipe_id}/report", status_code=204)
async def report_recipe(
    recipe_id: uuid.UUID,
    data: ReportIn,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Report a friend's recipe (App Store guideline 1.2). The team reviews
    reports in the database. You can't report your own."""
    recipe = await readable(db, user_id, recipe_id)
    if recipe.owner_id == user_id:
        raise HTTPException(422, "That's your own recipe.")
    reason = (data.reason or "").strip()
    try:
        db.add(ContentReport(
            reporter_id=user_id, reported_user_id=recipe.owner_id, kind="recipe", subject_id=recipe.id,
            reason=" | ".join(x for x in (reason, f"recipe: {recipe.title[:200]}") if x),
        ))
        await db.commit()
    except Exception:  # noqa: BLE001
        await db.rollback()
        log.exception("recipe report not saved")
        raise HTTPException(503, "Couldn't send that report. Please try again.")
    return Response(status_code=204)
