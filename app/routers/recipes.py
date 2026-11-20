import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user_id
from app.models.food_log import FoodLog
from app.models.message import Message, MessageAttachment
from app.models.recipe import Collection, CollectionItem, Recipe, RecipeEvent, RecipeIngredient, RecipeMedia, RecipeShare
from app.models.user import Profile
from app.core.rate_limit import messages_sent
from app.routers.logs import _out as _log_out, _write_nutrients
from app.routers.messages import _friend_ids, _out as _message_out, _require_friend
from app.schemas.messages import MessageOut
from app.schemas.recipes import RecipeIn, RecipeLogIn, RecipeUpdate, ShareIn
from app.services import avatars, recipe_photos, storage_service, usda_service
from app.services.nutrients import NUTRIENT_KEYS
from app.services.recipe_nutrition import Ingredient, PerServing, compute_per_serving, scale

log = logging.getLogger("calorie_backend")

router = APIRouter(prefix="/recipes", tags=["recipes"])

_EXTRAS = {k: f"{k}_per_100g" for k in NUTRIENT_KEYS}


def _unavailable() -> HTTPException:
    return HTTPException(status_code=503, detail="Recipes aren't available right now. Please try again later.")


def _ingredient_out(i: RecipeIngredient) -> dict:
    return {
        "position": i.position,
        "name": i.name,
        "grams": float(i.grams),
        "fdc_id": i.fdc_id,
        "source": i.source,
        "is_baseline": i.is_baseline,
        "calories_per_100g": i.calories_per_100g,
        "protein_g_per_100g": i.protein_g_per_100g,
        "carbs_g_per_100g": i.carbs_g_per_100g,
        "fat_g_per_100g": i.fat_g_per_100g,
    }


def _out(
    r: Recipe,
    ingredients: list[RecipeIngredient] | None = None,
    mine: bool = True,
    owner_name: str | None = None,
    cover_url: str | None = None,
) -> dict:
    out = {
        "id": str(r.id),
        "mine": mine,
        "owner_name": owner_name,
        "title": r.title,
        "description": r.description,
        "servings": float(r.servings),
        "visibility": r.visibility,
        "region": r.region,
        "tags": r.tags or [],
        "steps": r.steps or [],
        "calories_per_serving": r.calories_per_serving,
        "protein_g": r.protein_g,
        "carbs_g": r.carbs_g,
        "fat_g": r.fat_g,
        "nutrients": r.nutrients or None,
        "basis": r.basis,
        # "estimated" is the honest label for anything the author typed in.
        "estimated": r.basis != "ingredients",
        "cover_url": cover_url,
    }
    if ingredients is not None:
        out["ingredients"] = [_ingredient_out(i) for i in ingredients]
    return out


async def _resolve(items) -> list[Ingredient]:
    """Turn what the author sent into ingredients with known per-100 g values.
    Anything that can't be priced is refused by name, so a recipe never holds a
    silent zero."""
    by_id: dict = {}
    ids = [i.fdc_id for i in items if i.fdc_id]
    try:
        by_id = await usda_service.get_foods_by_ids(ids)
    except Exception:  # noqa: BLE001
        log.warning("recipe ingredient lookup failed", exc_info=True)
        raise HTTPException(status_code=503, detail="Couldn't look up the ingredients right now. Please try again.")

    out: list[Ingredient] = []
    for item in items:
        found = None
        manual = None
        if item.fdc_id:
            found = by_id.get(item.fdc_id)
        elif item.per_100g is not None:
            manual = item.per_100g
        else:
            try:
                found = await usda_service.get_best_match(item.name)
            except Exception:  # noqa: BLE001
                log.warning("recipe ingredient search failed", exc_info=True)
                raise HTTPException(status_code=503, detail="Couldn't look up the ingredients right now. Please try again.")
        if found is not None and found.calories_per_100g is not None:
            out.append(Ingredient(
                name=item.name, grams=item.grams, source="usda", fdc_id=found.fdc_id,
                calories_per_100g=found.calories_per_100g,
                protein_g_per_100g=found.protein_g_per_100g or 0,
                carbs_g_per_100g=found.carbs_g_per_100g or 0,
                fat_g_per_100g=found.fat_g_per_100g or 0,
                nutrients_per_100g={
                    k: v for k, attr in _EXTRAS.items() if (v := getattr(found, attr)) is not None
                },
                is_baseline=item.is_baseline,
            ))
        elif manual is not None:
            out.append(Ingredient(
                name=item.name, grams=item.grams, source="manual", fdc_id=None,
                calories_per_100g=manual.calories, protein_g_per_100g=manual.protein_g,
                carbs_g_per_100g=manual.carbs_g, fat_g_per_100g=manual.fat_g,
                is_baseline=item.is_baseline,
            ))
        else:
            raise HTTPException(
                status_code=422,
                detail=f"We couldn't find nutrition for “{item.name}”. Pick it from the search, or type its calories per 100 g.",
            )
    return out


async def _record_event(db: AsyncSession, recipe_id, actor_id, kind: str, log_entry_id: str | None = None) -> None:
    """Best effort, in a savepoint: never fails the thing the person did."""
    try:
        async with db.begin_nested():
            db.add(RecipeEvent(recipe_id=recipe_id, actor_id=actor_id, kind=kind, log_entry_id=log_entry_id))
    except Exception:  # noqa: BLE001
        log.warning("recipe event not recorded", exc_info=True)


async def _has_log_event(db: AsyncSession, recipe_id, log_entry_id: str) -> bool:
    try:
        async with db.begin_nested():
            found = (
                await db.execute(
                    select(RecipeEvent.id).where(
                        RecipeEvent.recipe_id == recipe_id,
                        RecipeEvent.kind == "log",
                        RecipeEvent.log_entry_id == log_entry_id,
                    ).limit(1)
                )
            ).scalar_one_or_none()
        return found is not None
    except Exception:  # noqa: BLE001
        return True  # can't tell: don't risk counting it twice


async def _mine(db: AsyncSession, user_id, recipe_id: uuid.UUID) -> Recipe:
    recipe = await db.get(Recipe, recipe_id)
    # Someone else's recipe is "not found", the same as one that doesn't exist.
    if recipe is None or recipe.owner_id != user_id or recipe.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Recipe not found")
    return recipe


async def readable(db: AsyncSession, user_id, recipe_id: uuid.UUID) -> Recipe:
    """A recipe I may open: my own, or a friend's that is set to "friends", or
    one a friend shared with me. Only while we are still friends (blocking or
    unfriending ends access at once). Anything else is "not found"."""
    recipe = await db.get(Recipe, recipe_id)
    if recipe is None or recipe.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Recipe not found")
    if recipe.owner_id == user_id:
        return recipe
    if recipe.visibility != "friends":
        try:
            async with db.begin_nested():
                shared = (
                    await db.execute(
                        select(RecipeShare.recipe_id).where(RecipeShare.recipe_id == recipe_id, RecipeShare.friend_id == user_id)
                    )
                ).first()
        except Exception:  # noqa: BLE001
            shared = None
        if shared is None:
            raise HTTPException(status_code=404, detail="Recipe not found")
    if recipe.owner_id not in await _friend_ids(db, user_id):
        raise HTTPException(status_code=404, detail="Recipe not found")
    return recipe


async def _owner_name(db: AsyncSession, owner_id) -> str | None:
    return (await db.execute(select(Profile.username).where(Profile.id == owner_id))).scalar_one_or_none()


async def _ingredients_of(db: AsyncSession, recipe_id) -> list[RecipeIngredient]:
    return list(
        (await db.execute(select(RecipeIngredient).where(RecipeIngredient.recipe_id == recipe_id).order_by(RecipeIngredient.position)))
        .scalars()
        .all()
    )


def _ingredient_rows(recipe_id, resolved: list[Ingredient]) -> list[RecipeIngredient]:
    return [
        RecipeIngredient(
            recipe_id=recipe_id, position=n, name=i.name, grams=i.grams, fdc_id=i.fdc_id, source=i.source,
            calories_per_100g=i.calories_per_100g, protein_g_per_100g=i.protein_g_per_100g,
            carbs_g_per_100g=i.carbs_g_per_100g, fat_g_per_100g=i.fat_g_per_100g,
            nutrients_per_100g=i.nutrients_per_100g or None, is_baseline=i.is_baseline,
        )
        for n, i in enumerate(resolved)
    ]


def _as_ingredients(rows: list[RecipeIngredient]) -> list[Ingredient]:
    return [
        Ingredient(
            i.name, float(i.grams), i.source, i.fdc_id, i.calories_per_100g, i.protein_g_per_100g,
            i.carbs_g_per_100g, i.fat_g_per_100g, i.nutrients_per_100g or {}, i.is_baseline,
        )
        for i in rows
    ]


@router.post("", status_code=201)
async def create_recipe(
    data: RecipeIn,
    response: Response,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Save a recipe. Its numbers come from the ingredients (USDA), or, for a
    recipe with no ingredient list, from the author's own estimate (shown as
    estimated). The id is chosen by the app, so a retry after a lost response
    returns the saved recipe instead of a copy."""
    try:
        existing = await db.get(Recipe, data.id)
    except Exception:  # noqa: BLE001
        await db.rollback()
        log.exception("recipes table not readable")
        raise _unavailable()
    if existing is not None:
        if existing.owner_id != user_id:
            raise HTTPException(status_code=409, detail="Recipe with this id already exists")
        response.status_code = 200
        return _out(existing, await _ingredients_of(db, existing.id))

    resolved: list[Ingredient] = []
    if data.ingredients:
        resolved = await _resolve(data.ingredients)
        ps = compute_per_serving(resolved, data.servings)
    else:
        p = data.per_serving
        known = data.nutrients.known() if data.nutrients else {}
        ps = PerServing(p.calories, p.protein_g, p.carbs_g, p.fat_g, known, "manual")

    recipe = Recipe(
        id=data.id, owner_id=user_id, title=data.title, description=data.description,
        servings=data.servings, visibility="private", region=data.region, tags=data.tags, steps=data.steps,
        calories_per_serving=ps.calories, protein_g=ps.protein_g, carbs_g=ps.carbs_g, fat_g=ps.fat_g,
        nutrients=ps.nutrients or None, basis=ps.basis,
    )
    rows = _ingredient_rows(data.id, resolved)
    try:
        db.add(recipe)
        await db.flush()  # the recipe row must exist before its ingredients
        db.add_all(rows)
        await db.commit()
    except Exception:  # noqa: BLE001
        await db.rollback()
        log.exception("recipe not saved")
        raise _unavailable()
    return _out(recipe, rows)


@router.get("")
async def list_recipes(user_id: uuid.UUID = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    try:
        rows = (
            await db.execute(
                select(Recipe)
                .where(Recipe.owner_id == user_id, Recipe.deleted_at.is_(None))
                .order_by(Recipe.created_at.desc())
                .limit(200)
            )
        ).scalars().all()
    except Exception:  # noqa: BLE001
        # Without the migration there are simply no recipes yet.
        await db.rollback()
        log.warning("recipes not readable", exc_info=True)
        return []
    covers = await recipe_photos.covers(db, [r.id for r in rows])
    return [_out(r, cover_url=covers.get(r.id)) for r in rows]


@router.get("/{recipe_id}")
async def get_recipe(recipe_id: uuid.UUID, user_id: uuid.UUID = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    recipe = await readable(db, user_id, recipe_id)
    mine = recipe.owner_id == user_id
    photos = await recipe_photos.media(db, recipe.id)
    out = _out(
        recipe, await _ingredients_of(db, recipe.id), mine=mine,
        owner_name=None if mine else await _owner_name(db, recipe.owner_id),
        cover_url=next((m["url"] for m in photos if m["position"] == recipe_photos.COVER), None),
    )
    out["media"] = [m for m in photos if m["position"] != recipe_photos.COVER]
    return out


@router.get("/{recipe_id}/shares")
async def list_shares(recipe_id: uuid.UUID, user_id: uuid.UUID = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    """Who I have shared this recipe with, so I can take it back. Only the owner
    can see this list. Rows stay until revoked, even if the friendship ended, so
    an old share can never quietly come back to life."""
    recipe = await _mine(db, user_id, recipe_id)
    try:
        async with db.begin_nested():
            rows = (
                await db.execute(
                    select(RecipeShare.friend_id, Profile.username, RecipeShare.created_at)
                    .join(Profile, Profile.id == RecipeShare.friend_id)
                    .where(RecipeShare.recipe_id == recipe.id)
                    .order_by(RecipeShare.created_at.desc())
                )
            ).all()
    except Exception:  # noqa: BLE001
        log.warning("shares not readable", exc_info=True)
        return []
    pictures = await avatars.avatar_urls(db, [f for f, _, _ in rows])
    return [
        {"friend_id": str(f), "username": name, "avatar_url": pictures.get(f), "shared_at": at.isoformat() if at else None}
        for f, name, at in rows
    ]


@router.patch("/{recipe_id}")
async def update_recipe(
    recipe_id: uuid.UUID,
    data: RecipeUpdate,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    recipe = await _mine(db, user_id, recipe_id)
    changes = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
    if "title" in changes:
        changes["title"] = changes["title"].strip()
        if not changes["title"]:
            raise HTTPException(status_code=422, detail="The title can't be empty.")
    ingredients = await _ingredients_of(db, recipe.id)
    for field in ("title", "description", "region", "tags", "steps", "visibility"):
        if field in changes:
            setattr(recipe, field, changes[field])
    new_servings = changes.get("servings", float(recipe.servings))
    replaced = None
    if "ingredients" in changes:
        # Priced again on the server, with the same refusal-by-name rule as a new
        # recipe. Entries already logged from this recipe are plain entries and
        # keep their numbers.
        resolved = await _resolve(data.ingredients)
        replaced = _ingredient_rows(recipe.id, resolved)
        ps = compute_per_serving(resolved, new_servings)
        recipe.basis = ps.basis
    elif "servings" in changes and changes["servings"] != float(recipe.servings) and ingredients:
        # Numbers are per serving, so a new serving count re-divides the same
        # ingredients. A recipe with no ingredient list keeps its own numbers.
        ps = compute_per_serving(_as_ingredients(ingredients), new_servings)
    else:
        ps = None
    if "servings" in changes:
        recipe.servings = changes["servings"]
    if ps is not None:
        recipe.calories_per_serving, recipe.protein_g, recipe.carbs_g, recipe.fat_g = ps.calories, ps.protein_g, ps.carbs_g, ps.fat_g
        recipe.nutrients = ps.nutrients or None
    recipe.updated_at = datetime.now(timezone.utc)
    try:
        if replaced is not None:
            await db.execute(delete(RecipeIngredient).where(RecipeIngredient.recipe_id == recipe.id))
            db.add_all(replaced)
            ingredients = replaced
        await db.commit()
    except Exception:  # noqa: BLE001
        await db.rollback()
        log.exception("recipe update failed")
        raise _unavailable()
    return _out(recipe, ingredients)


@router.delete("/{recipe_id}", status_code=204)
async def delete_recipe(recipe_id: uuid.UUID, user_id: uuid.UUID = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    """Soft delete: entries already logged from it keep their numbers, and past
    logs stay countable for any later creator program."""
    recipe = await _mine(db, user_id, recipe_id)
    recipe.deleted_at = datetime.now(timezone.utc)
    # The photos go with it (a deleted recipe is gone for everyone); the rows
    # needed for later payouts are the events, not the pictures.
    photo_paths = await recipe_photos.paths_of(db, recipe.id) if storage_service.configured() else []
    try:
        if photo_paths:
            await db.execute(delete(RecipeMedia).where(RecipeMedia.recipe_id == recipe.id))
        await db.commit()
    except Exception:  # noqa: BLE001
        await db.rollback()
        log.exception("recipe delete failed")
        raise _unavailable()
    if photo_paths:
        try:
            await storage_service.delete(photo_paths)
        except storage_service.StorageUnavailable:
            log.warning("could not delete recipe photos %s", photo_paths)
    return Response(status_code=204)


@router.post("/{recipe_id}/log", status_code=201)
async def log_recipe(
    recipe_id: uuid.UUID,
    data: RecipeLogIn,
    response: Response,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Log some servings of a recipe in one tap: one food-log entry named after
    the recipe. Idempotent on the entry id, like POST /logs.

    Saved with source "manual": the app reads `source` as one of its two known
    values, and a new one would break loading the day in every installed build.
    """
    recipe = await readable(db, user_id, recipe_id)
    existing = await db.get(FoodLog, data.id)
    if existing is not None:
        if existing.user_id != user_id:
            raise HTTPException(status_code=409, detail="Log with this id already exists")
        response.status_code = 200
        # The app saves the entry through its normal offline-safe path first and
        # reports the recipe afterwards, so the entry may already be here. The
        # event is still recorded, once.
        if not await _has_log_event(db, recipe.id, data.id):
            await _record_event(db, recipe.id, user_id, "log", data.id)
            try:
                await db.commit()
            except Exception:  # noqa: BLE001
                await db.rollback()
                log.warning("recipe event not saved", exc_info=True)
        return _log_out(existing, None)

    amounts = scale(
        {
            "calories": recipe.calories_per_serving, "protein_g": recipe.protein_g,
            "carbs_g": recipe.carbs_g, "fat_g": recipe.fat_g, "nutrients": recipe.nutrients,
        },
        data.servings,
    )
    entry = FoodLog(
        id=data.id, user_id=user_id, name=recipe.title[:500], calories=amounts["calories"],
        protein_g=amounts["protein_g"], carbs_g=amounts["carbs_g"], fat_g=amounts["fat_g"],
        meal_type=data.meal_type, source="manual", log_date=data.log_date, timestamp=data.timestamp,
    )
    db.add(entry)
    try:
        await db.commit()
    except Exception:  # noqa: BLE001
        await db.rollback()
        log.exception("recipe log failed")
        raise HTTPException(status_code=500, detail="Could not save this entry")
    nutrients = amounts["nutrients"] or None
    if nutrients:
        await _write_nutrients(db, data.id, nutrients)
    await _record_event(db, recipe.id, user_id, "log", data.id)
    try:
        await db.commit()
    except Exception:  # noqa: BLE001
        await db.rollback()
        log.warning("recipe log extras not saved", exc_info=True)
        nutrients = None
    return _log_out(entry, nutrients)


@router.post("/{recipe_id}/save", status_code=204)
async def save_recipe(recipe_id: uuid.UUID, user_id: uuid.UUID = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    """Keep a recipe (mine, or one a friend shared) in my "Saved" collection."""
    recipe = await readable(db, user_id, recipe_id)
    try:
        async with db.begin_nested():
            saved = (
                await db.execute(select(Collection).where(Collection.owner_id == user_id, Collection.is_default.is_(True)))
            ).scalars().first()
            if saved is None:
                saved = Collection(id=uuid.uuid4(), owner_id=user_id, name="Saved", is_default=True)
                db.add(saved)
                await db.flush()
            await db.execute(
                pg_insert(CollectionItem).values(collection_id=saved.id, recipe_id=recipe.id).on_conflict_do_nothing()
            )
        await _record_event(db, recipe.id, user_id, "save")
        await db.commit()
    except Exception:  # noqa: BLE001
        await db.rollback()
        log.exception("recipe not saved to collection")
        raise _unavailable()
    return Response(status_code=204)


@router.post("/{recipe_id}/share/{friend_id}", response_model=MessageOut)
async def share_recipe(
    recipe_id: uuid.UUID,
    friend_id: uuid.UUID,
    data: ShareIn,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Send one of my recipes to a friend as a chat card. It stays private: this
    one friend gets read access, which `DELETE` on the same path takes back.
    Repeating the request (same id) returns the first message."""
    recipe = await _mine(db, user_id, recipe_id)
    existing = await db.get(Message, data.id)
    if existing is not None:
        if existing.sender_id != user_id or existing.recipient_id != friend_id:
            raise HTTPException(status_code=409, detail="That message id is already used.")
        return _message_out(existing, user_id, None)

    await _require_friend(db, user_id, friend_id)
    messages_sent.check("message", user_id, "You're sending messages very fast. Try again in a moment.")

    card = {"kind": "recipe", "id": str(recipe.id), "title": recipe.title, "calories": recipe.calories_per_serving}
    message = Message(
        id=data.id, sender_id=user_id, recipient_id=friend_id,
        # What an app without recipe cards (or without the table) shows.
        body=f"Sent you a recipe: {recipe.title} ({recipe.calories_per_serving} kcal per serving)"[:1000],
        created_at=datetime.now(timezone.utc),
    )
    try:
        db.add(message)
        await db.flush()  # the attachment row refers to the message
        await db.execute(pg_insert(RecipeShare).values(recipe_id=recipe.id, friend_id=friend_id).on_conflict_do_nothing())
        await db.execute(pg_insert(MessageAttachment).values(message_id=data.id, attachment=card).on_conflict_do_nothing())
        await _record_event(db, recipe.id, user_id, "share")
        await db.commit()
    except Exception:  # noqa: BLE001
        await db.rollback()
        log.exception("recipe not shared")
        raise _unavailable()
    return _message_out(message, user_id, card)


@router.delete("/{recipe_id}/share/{friend_id}", status_code=204)
async def unshare_recipe(
    recipe_id: uuid.UUID,
    friend_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Take back a friend's access. The card stays in the chat but no longer opens."""
    recipe = await _mine(db, user_id, recipe_id)
    try:
        await db.execute(delete(RecipeShare).where(RecipeShare.recipe_id == recipe.id, RecipeShare.friend_id == friend_id))
        await db.commit()
    except Exception:  # noqa: BLE001
        await db.rollback()
        log.exception("recipe unshare failed")
        raise _unavailable()
    return Response(status_code=204)
