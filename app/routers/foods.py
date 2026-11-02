import logging
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.security import get_current_user_id
from app.models.food import FoodSearchResponse
from app.services.usda_service import search_foods

log = logging.getLogger("calorie_backend")

router = APIRouter(prefix="/foods", tags=["foods"])


@router.get("/search", response_model=FoodSearchResponse)
async def search(
    query: str = Query(..., max_length=200),
    page_size: int = Query(20, ge=1, le=50),
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """Proxies the metered USDA key, so it can't be an open relay.

    The client used to call USDA directly with the key compiled into the app,
    which shipped it in every web bundle and mobile build.
    """
    try:
        results = await search_foods(query, page_size=page_size)
    except (httpx.HTTPError, ValueError):
        # An unhandled error here is a 500 without CORS headers, which the web
        # client can only report as "Failed to fetch".
        log.exception("usda search failed")
        raise HTTPException(status_code=502, detail="Food search is temporarily unavailable")
    return FoodSearchResponse(query=query, results=results)
