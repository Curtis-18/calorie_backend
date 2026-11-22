import logging
import uuid

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.body_limit import BodyLimitMiddleware
from app.core.config import Settings, settings
from app.core.database import get_db
from app.core.security import get_current_user_id
from app.models.user import Profile
from app.services import avatars
from app.routers import (
    account, activity, adjustments, avatar, budget, coach, collections, recipe_media, foods, friends, insights, logs, messages, notifications, photo_estimation, prefs, progress, recipes, reports, snaps, stories, targets, username,
    weights, workouts,
)

# Import every model before the app serves traffic so Base.metadata knows
# about all tables and FK targets resolve.
from app.models import activity as activity_model, ai_usage, budget_prefs, coach_message, food_log, food_log_estimate, food_log_nutrients, friendship, insights_cache, message, notification, recipe, snap, story, target, user, user_language, user_prefs, weight_log  # noqa: F401

log = logging.getLogger("calorie_backend")


def cors_kwargs(cors: Settings) -> dict:
    """CORS config in one place, so tests exercise the real wiring.

    Origins come from CORS_ORIGINS. A hardcoded single origin meant every
    deployed frontend was rejected: the browser blocks the response before the
    app ever sees it, and the client reports a network failure rather than the
    400 the server actually returned. Entries containing `*` are matched as
    host wildcards, which is what keeps Vercel preview deploys working.
    """
    return {
        "allow_origins": cors.exact_origins,
        "allow_origin_regex": cors.cors_origin_regex,
        "allow_credentials": True,
        "allow_methods": ["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        "allow_headers": ["Authorization", "Content-Type"],
    }


app = FastAPI(
    title="Calorie Backend",
    # Trailing slashes would make /logs/ 404 against the client's /logs.
    redirect_slashes=False,
)

# The largest legitimate body is a base64 photo for /estimate-photo. Added
# before CORS so CORS stays outermost and a 413 still carries its headers.


@app.exception_handler(RequestValidationError)
async def log_refused_request(request: Request, exc: RequestValidationError):
    """Answer exactly as before (a 422 naming the fields), and leave a line in the
    server log saying which fields were refused and why. Render's access log shows
    only "422", so a refused save could not be diagnosed. Field names and rule
    names only: never the values, which can be a person's food, notes or messages."""
    problems = ", ".join(
        f"{'.'.join(str(part) for part in e.get('loc', ()) if part != 'body')}:{e.get('type')}" for e in exc.errors()[:8]
    )
    log.warning("request refused %s %s: %s", request.method, request.url.path, problems)
    return await request_validation_exception_handler(request, exc)


app.add_middleware(BodyLimitMiddleware, max_bytes=settings.max_photo_bytes * 4 // 3 + 64 * 1024)
app.add_middleware(CORSMiddleware, **cors_kwargs(settings))

app.include_router(foods.router)
app.include_router(adjustments.router)
app.include_router(budget.router)
app.include_router(prefs.router)
app.include_router(reports.router)
app.include_router(recipes.router)
app.include_router(recipe_media.router)
app.include_router(collections.router)
app.include_router(logs.router)
app.include_router(targets.router)
app.include_router(insights.router)
app.include_router(photo_estimation.router)
app.include_router(progress.router)
app.include_router(weights.router)
app.include_router(username.router)
app.include_router(friends.router)
app.include_router(snaps.router)
app.include_router(notifications.router)
app.include_router(activity.router)
app.include_router(account.router)
app.include_router(avatar.router)
app.include_router(stories.router)
app.include_router(messages.router)
app.include_router(coach.router)
app.include_router(workouts.router)


@app.get("/")
async def root():
    return {"status": "ok"}


@app.get("/health")
async def health(db: AsyncSession = Depends(get_db)):
    """Liveness plus a real DB round-trip, so Render restarts us if the pooler dies."""
    try:
        await db.execute(text("select 1"))
    except Exception as exc:  # noqa: BLE001 - never leak driver internals to the probe
        log.exception("health check failed")
        # Must be a real JSONResponse. Returning a Flask-style `(body, 503)`
        # tuple made FastAPI serialise the tuple as a JSON list with a 200, so
        # Render saw a healthy service and never restarted it on DB loss.
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "database": "unreachable", "detail": type(exc).__name__},
        )
    return {"status": "ok", "database": "ok"}


@app.get("/me")
async def me(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Who am I. `username` is None until the user picks one, which is how the
    app knows to ask."""
    try:
        username = (
            await db.execute(select(Profile.username).where(Profile.id == user_id))
        ).scalar_one_or_none()
    except Exception:  # noqa: BLE001
        # This used to answer `username: null`, which the app reads as "this
        # person has no username": one database hiccup sent someone who had a
        # name to the pick-a-username screen, where their own name then showed
        # as taken. A 503 tells the app it simply doesn't know.
        log.exception("could not read username")
        raise HTTPException(status_code=503, detail="Couldn't load your account. Please try again.")
    # Never fails: no picture (or no way to read one) is simply None.
    picture = (await avatars.avatar_urls(db, [user_id])).get(user_id)
    return {"user_id": str(user_id), "username": username, "avatar_url": picture}
