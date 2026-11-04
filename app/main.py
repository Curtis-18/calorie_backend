import logging
import uuid

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, settings
from app.core.database import get_db
from app.core.security import get_current_user_id
from app.models.user import Profile
from app.routers import foods, friends, insights, logs, photo_estimation, progress, targets, username, weights

# Import every model before the app serves traffic so Base.metadata knows
# about all tables and FK targets resolve.
from app.models import food_log, friendship, insights_cache, target, user, weight_log  # noqa: F401

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
        "allow_methods": ["GET", "POST", "DELETE", "OPTIONS"],
        "allow_headers": ["Authorization", "Content-Type"],
    }


app = FastAPI(
    title="Calorie Backend",
    # Trailing slashes would make /logs/ 404 against the client's /logs.
    redirect_slashes=False,
)

app.add_middleware(CORSMiddleware, **cors_kwargs(settings))

app.include_router(foods.router)
app.include_router(logs.router)
app.include_router(targets.router)
app.include_router(insights.router)
app.include_router(photo_estimation.router)
app.include_router(progress.router)
app.include_router(weights.router)
app.include_router(username.router)
app.include_router(friends.router)


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
    """Who am I. `username` is None until the user picks one (every existing
    user, right after this ships), which is how the app knows to ask."""
    username = None
    try:
        username = (
            await db.execute(select(Profile.username).where(Profile.id == user_id))
        ).scalar_one_or_none()
    except Exception:  # noqa: BLE001 - the column may not exist until the migration is run
        log.exception("could not read username")
    return {"user_id": str(user_id), "username": username}
