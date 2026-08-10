import os

from fastapi import FastAPI, Depends
from app.routers import foods, logs, insights, photo_estimation
from app.core.security import get_current_user_id
from app.routers import targets
from fastapi.middleware.cors import CORSMiddleware

# Ensures all models are registered on Base.metadata before any request
# triggers mapper configuration. Without this, FK resolution to "profiles"
# fails at commit time if nothing else in the import chain touches
# models/user.py directly.
from app.models import user, target, food_log, insights_cache  # noqa: F401
#from app.models import user, target, food_log, insights_cache  # noqa: F401

app = FastAPI(title="Calorie Backend")

app.include_router(foods.router)
app.include_router(logs.router)
app.include_router(targets.router)
app.include_router(insights.router)
app.include_router(photo_estimation.router)

frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[frontend_url],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"status": "ok"}


@app.get("/me")
def me(user_id: str = Depends(get_current_user_id)):
    return {"user_id": user_id}