import uuid
from datetime import date as date_type

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dates import resolve_today
from app.core.security import get_current_user_id
from app.schemas.progress import ProgressOut
from app.core.language import get_language
from app.services.progress_read import load_progress

router = APIRouter(prefix="/progress", tags=["progress"])


@router.get("", response_model=ProgressOut)
async def get_progress(
    date: date_type | None = None,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
    lang: str = Depends(get_language),
):
    """Streak, freezes, XP, level and achievements, derived from the logs.

    `date` is the device-local "today" (see resolve_today), so the streak
    agrees with the day the user is actually on. The loading lives in
    progress_read, shared with the badge/level notifications so they agree.
    """
    today = resolve_today(date)
    return await load_progress(db, user_id, today, lang)
