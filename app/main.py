import logging

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user_id
from app.routers import foods, insights, logs, photo_estimation, targets

# Import every model before the app serves traffic so Base.metadata knows
# about all tables and FK targets resolve.
from app.models import food_log, insights_cache, target, user  # noqa: F401

log = logging.getLogger("calorie_backend")

app = FastAPI(
    title="Calorie Backend",
    # Trailing slashes would make /logs/ 404 against the client's /logs.
    redirect_slashes=False,
)

app.add_middleware(
    CORSMiddleware,
    # A single hardcoded origin meant every deployed frontend origin was
    # rejected: browsers block the response before the app ever sees it.
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(foods.router)
app.include_router(logs.router)
app.include_router(targets.router)
app.include_router(insights.router)
app.include_router(photo_estimation.router)


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
        return {"status": "degraded", "database": "unreachable", "detail": type(exc).__name__}, 503
    return {"status": "ok", "database": "ok"}


@app.get("/me")
async def me(user_id: str = Depends(get_current_user_id)):
    return {"user_id": str(user_id)}
