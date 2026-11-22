import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user_id
from app.schemas.activity import ActivityOut
from app.services import activity

router = APIRouter(prefix="/activity", tags=["activity"])


@router.get("", response_model=ActivityOut)
async def list_activity(user_id: uuid.UUID = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    """Bites and reactions from friends, newest first, and how many are unseen.
    Messages and friend requests are not part of this list."""
    return await activity.feed(db, user_id)


@router.post("/seen", status_code=204)
async def mark_seen(user_id: uuid.UUID = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    """Opening the Notifications screen: everything so far counts as seen."""
    await activity.mark_seen(db, user_id)
    return None
