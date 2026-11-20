"""Collections (folders of recipes) and Highlights (up to six pinned recipes)."""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user_id
from app.models.recipe import Collection, CollectionItem, Recipe, RecipePin, RecipeShare
from app.routers.messages import _friend_ids
from app.routers.recipes import _unavailable, readable
from app.services import recipe_photos
from app.schemas.recipes import CollectionIn, CollectionItemIn, HighlightsIn

log = logging.getLogger("calorie_backend")

router = APIRouter(tags=["collections"])

MAX_COLLECTIONS = 20


def _summary(r: Recipe, me: uuid.UUID, cover_url: str | None = None) -> dict:
    return {
        "id": str(r.id),
        "cover_url": cover_url,
        "title": r.title,
        "calories_per_serving": r.calories_per_serving,
        "estimated": r.basis != "ingredients",
        "mine": r.owner_id == me,
    }


async def _my_collection(db: AsyncSession, user_id, collection_id: uuid.UUID) -> Collection:
    found = await db.get(Collection, collection_id)
    if found is None or found.owner_id != user_id:
        raise HTTPException(status_code=404, detail="Collection not found")
    return found


@router.get("/collections")
async def list_collections(user_id: uuid.UUID = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    """My collections with the recipes in them. A recipe that was deleted, or a
    friend's recipe that is no longer shared with me, simply isn't listed."""
    try:
        collections = (
            await db.execute(select(Collection).where(Collection.owner_id == user_id).order_by(Collection.is_default.desc(), Collection.created_at))
        ).scalars().all()
        if not collections:
            return []
        items = (
            await db.execute(
                select(CollectionItem.collection_id, CollectionItem.recipe_id, CollectionItem.added_at)
                .where(CollectionItem.collection_id.in_([c.id for c in collections]))
                .order_by(CollectionItem.added_at.desc())
            )
        ).all()
        recipe_ids = {rid for _, rid, _ in items}
        recipes = {}
        if recipe_ids:
            recipes = {
                r.id: r
                for r in (
                    await db.execute(select(Recipe).where(Recipe.id.in_(recipe_ids), Recipe.deleted_at.is_(None)))
                ).scalars().all()
            }
        others = {r.id for r in recipes.values() if r.owner_id != user_id}
        shared_with_me: set = set()
        friends: set = set()
        if others:
            shared_with_me = {
                rid
                for (rid,) in (
                    await db.execute(select(RecipeShare.recipe_id).where(RecipeShare.recipe_id.in_(others), RecipeShare.friend_id == user_id))
                ).all()
            }
            friends = await _friend_ids(db, user_id)
    except Exception:  # noqa: BLE001
        # Without the migration there are simply no collections yet.
        await db.rollback()
        log.warning("collections not readable", exc_info=True)
        return []

    def allowed(r: Recipe) -> bool:
        if r.owner_id == user_id:
            return True
        return r.owner_id in friends and (r.visibility == "friends" or r.id in shared_with_me)

    covers = await recipe_photos.covers(db, [rid for rid, r in recipes.items() if allowed(r)])
    out = []
    for c in collections:
        mine = [recipes[rid] for cid, rid, _ in items if cid == c.id and rid in recipes and allowed(recipes[rid])]
        out.append({
            "id": str(c.id), "name": c.name, "is_default": c.is_default,
            "items": [_summary(r, user_id, covers.get(r.id)) for r in mine],
        })
    return out


@router.post("/collections", status_code=201)
async def create_collection(
    data: CollectionIn,
    response: Response,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    try:
        existing = await db.get(Collection, data.id)
        if existing is not None:
            if existing.owner_id != user_id:
                raise HTTPException(status_code=409, detail="Collection with this id already exists")
            response.status_code = 200
            return {"id": str(existing.id), "name": existing.name, "is_default": existing.is_default, "items": []}
        count = (await db.execute(select(func.count()).select_from(Collection).where(Collection.owner_id == user_id))).scalar_one()
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        await db.rollback()
        log.exception("collections not readable")
        raise _unavailable()
    if count >= MAX_COLLECTIONS:
        raise HTTPException(status_code=422, detail=f"You can have up to {MAX_COLLECTIONS} collections.")
    collection = Collection(id=data.id, owner_id=user_id, name=data.name, is_default=False)
    try:
        db.add(collection)
        await db.commit()
    except Exception:  # noqa: BLE001
        await db.rollback()
        log.exception("collection not saved")
        raise _unavailable()
    return {"id": str(collection.id), "name": collection.name, "is_default": False, "items": []}


@router.delete("/collections/{collection_id}", status_code=204)
async def delete_collection(collection_id: uuid.UUID, user_id: uuid.UUID = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    """Delete a folder. The recipes in it are untouched."""
    collection = await _my_collection(db, user_id, collection_id)
    if collection.is_default:
        raise HTTPException(status_code=422, detail="The Saved collection can't be deleted.")
    try:
        await db.delete(collection)
        await db.commit()
    except Exception:  # noqa: BLE001
        await db.rollback()
        log.exception("collection delete failed")
        raise _unavailable()
    return Response(status_code=204)


@router.post("/collections/{collection_id}/items", status_code=204)
async def add_item(
    collection_id: uuid.UUID,
    data: CollectionItemIn,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    collection = await _my_collection(db, user_id, collection_id)
    recipe = await readable(db, user_id, data.recipe_id)
    try:
        await db.execute(pg_insert(CollectionItem).values(collection_id=collection.id, recipe_id=recipe.id).on_conflict_do_nothing())
        await db.commit()
    except Exception:  # noqa: BLE001
        await db.rollback()
        log.exception("collection item not saved")
        raise _unavailable()
    return Response(status_code=204)


@router.delete("/collections/{collection_id}/items/{recipe_id}", status_code=204)
async def remove_item(
    collection_id: uuid.UUID,
    recipe_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    collection = await _my_collection(db, user_id, collection_id)
    try:
        await db.execute(delete(CollectionItem).where(CollectionItem.collection_id == collection.id, CollectionItem.recipe_id == recipe_id))
        await db.commit()
    except Exception:  # noqa: BLE001
        await db.rollback()
        log.exception("collection item not removed")
        raise _unavailable()
    return Response(status_code=204)


@router.get("/highlights")
async def get_highlights(user_id: uuid.UUID = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    """My pinned recipes, in order."""
    try:
        rows = (
            await db.execute(
                select(Recipe)
                .join(RecipePin, RecipePin.recipe_id == Recipe.id)
                .where(RecipePin.user_id == user_id, Recipe.deleted_at.is_(None), Recipe.owner_id == user_id)
                .order_by(RecipePin.position)
            )
        ).scalars().all()
    except Exception:  # noqa: BLE001
        await db.rollback()
        log.warning("highlights not readable", exc_info=True)
        return []
    covers = await recipe_photos.covers(db, [r.id for r in rows])
    return [_summary(r, user_id, covers.get(r.id)) for r in rows]


@router.get("/users/{friend_id}/highlights")
async def friend_highlights(
    friend_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """A friend's Highlights: only the pinned recipes I am allowed to open (set
    to "friends", or shared with me). Anyone who is not a friend, including
    someone blocked, gets "not found". No counts, no totals."""
    if friend_id == user_id:
        return await get_highlights(user_id, db)
    try:
        if friend_id not in await _friend_ids(db, user_id):
            raise HTTPException(status_code=404, detail="Not found")
        rows = (
            await db.execute(
                select(Recipe)
                .join(RecipePin, RecipePin.recipe_id == Recipe.id)
                .where(RecipePin.user_id == friend_id, Recipe.owner_id == friend_id, Recipe.deleted_at.is_(None))
                .order_by(RecipePin.position)
            )
        ).scalars().all()
        private = [r.id for r in rows if r.visibility != "friends"]
        shared: set = set()
        if private:
            shared = {
                rid
                for (rid,) in (
                    await db.execute(select(RecipeShare.recipe_id).where(RecipeShare.recipe_id.in_(private), RecipeShare.friend_id == user_id))
                ).all()
            }
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        await db.rollback()
        log.warning("friend highlights not readable", exc_info=True)
        return []
    shown = [r for r in rows if r.visibility == "friends" or r.id in shared]
    covers = await recipe_photos.covers(db, [r.id for r in shown])
    return [_summary(r, user_id, covers.get(r.id)) for r in shown]


@router.put("/highlights")
async def set_highlights(data: HighlightsIn, user_id: uuid.UUID = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    """Replace my Highlights with these recipes, in this order (at most six,
    all my own). Repeating the request changes nothing."""
    try:
        owned = set(
            (await db.execute(select(Recipe.id).where(Recipe.id.in_(data.recipe_ids), Recipe.owner_id == user_id, Recipe.deleted_at.is_(None)))).scalars().all()
        ) if data.recipe_ids else set()
    except Exception:  # noqa: BLE001
        await db.rollback()
        log.exception("highlights not readable")
        raise _unavailable()
    if owned != set(data.recipe_ids):
        raise HTTPException(status_code=422, detail="You can only pin your own recipes.")
    try:
        await db.execute(delete(RecipePin).where(RecipePin.user_id == user_id))
        for position, rid in enumerate(data.recipe_ids):
            db.add(RecipePin(user_id=user_id, recipe_id=rid, position=position))
        await db.commit()
    except Exception:  # noqa: BLE001
        await db.rollback()
        log.exception("highlights not saved")
        raise _unavailable()
    return {"recipe_ids": [str(r) for r in data.recipe_ids]}
