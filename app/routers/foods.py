import logging
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.rate_limit import food_searches
from app.core.security import get_current_user_id
from app.models.food import FoodSearchResponse, FoodSearchResult
from app.services.usda_service import lookup_barcode, normalize_barcode, search_foods

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
    food_searches.check("search", user_id, "You're searching very fast. Wait a moment and try again.")
    try:
        results = await search_foods(query, page_size=page_size)
    except (httpx.HTTPError, ValueError):
        # An unhandled error here is a 500 without CORS headers, which the web
        # client can only report as "Failed to fetch".
        log.exception("usda search failed")
        raise HTTPException(status_code=502, detail="Food search is temporarily unavailable")
    return FoodSearchResponse(query=query, results=results)


@router.get("/barcode", response_model=FoodSearchResult)
async def barcode(
    code: str = Query(..., max_length=32),
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """A packaged food by its barcode (USDA Branded foods). 404 when USDA has none.

    Never limited by the Pro tier: barcode logging stays free (handover:
    PRODUCT ROADMAP P6.2).
    """
    digits = normalize_barcode(code)
    if digits is None:
        raise HTTPException(status_code=422, detail="That doesn't look like a barcode")
    food_searches.check("search", user_id, "You're searching very fast. Wait a moment and try again.")
    try:
        found = await lookup_barcode(digits)
    except (httpx.HTTPError, ValueError):
        log.exception("usda barcode lookup failed")
        raise HTTPException(status_code=502, detail="Food search is temporarily unavailable")
    if found is None:
        raise HTTPException(status_code=404, detail="We couldn't find that product. Try searching by name.")
    return found
