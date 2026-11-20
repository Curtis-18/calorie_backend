"""Recipe photos: the cover (position 0) and carousel slides (1-5).

The files sit in the private bucket, so the app is handed short-lived signed
links. Reading photos is never worth failing a request for: a missing table
(migration not run) or a signing error simply means no photos.
"""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.recipe import RecipeMedia
from app.services import storage_service
from app.services.storage_service import StorageUnavailable

log = logging.getLogger("calorie_backend")

COVER = 0
MAX_SLIDES = 5


async def _rows(db: AsyncSession, recipe_ids: list, cover_only: bool) -> list:
    query = select(RecipeMedia.recipe_id, RecipeMedia.position, RecipeMedia.path, RecipeMedia.caption).where(
        RecipeMedia.recipe_id.in_(recipe_ids)
    )
    if cover_only:
        query = query.where(RecipeMedia.position == COVER)
    try:
        async with db.begin_nested():
            return list((await db.execute(query.order_by(RecipeMedia.position))).all())
    except Exception:  # noqa: BLE001
        log.warning("could not read recipe photos", exc_info=True)
        return []


async def signed_links(paths: list[str]) -> dict[str, str | None]:
    try:
        return await storage_service.sign(paths)
    except StorageUnavailable:
        log.warning("could not sign recipe photo links", exc_info=True)
        return {}


async def covers(db: AsyncSession, recipe_ids) -> dict[uuid.UUID, str]:
    """A viewing link for the cover of each recipe that has one."""
    ids = list(dict.fromkeys(recipe_ids))
    if not ids or not storage_service.configured():
        return {}
    rows = await _rows(db, ids, cover_only=True)
    if not rows:
        return {}
    links = await signed_links([p for _, _, p, _ in rows])
    return {rid: links[p] for rid, _, p, _ in rows if links.get(p)}


async def media(db: AsyncSession, recipe_id) -> list[dict]:
    """Every photo of one recipe, in order, each with a viewing link."""
    if not storage_service.configured():
        return []
    rows = await _rows(db, [recipe_id], cover_only=False)
    if not rows:
        return []
    links = await signed_links([p for _, _, p, _ in rows])
    return [
        {"position": pos, "caption": caption, "url": links[path]}
        for _, pos, path, caption in rows
        if links.get(path)
    ]


async def paths_of(db: AsyncSession, recipe_id) -> list[str]:
    return [p for _, _, p, _ in await _rows(db, [recipe_id], cover_only=False)]
