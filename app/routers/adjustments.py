import logging
import uuid

from fastapi import APIRouter, Depends

from app.core.rate_limit import food_searches
from app.core.security import get_current_user_id
from app.services.adjustments import list_adjustments

log = logging.getLogger("calorie_backend")

router = APIRouter(prefix="/adjustments", tags=["adjustments"])


@router.get("")
async def adjustments(user_id: uuid.UUID = Depends(get_current_user_id)):
    """The one-tap extras for the photo review screen (oil, butter, dressing...).

    Served from the server so amounts and values can change without an app
    release. Never limited by the Pro tier.
    """
    food_searches.check("search", user_id, "You're searching very fast. Wait a moment and try again.")
    return await list_adjustments()
