import uuid

from fastapi import APIRouter, Depends

from app.core.security import get_current_user_id
from app.models.food import FoodSearchResponse
from app.services.usda_service import search_foods

router = APIRouter(prefix="/foods", tags=["foods"])


@router.get("/search", response_model=FoodSearchResponse)
async def search(
    query: str,
    user_id: uuid.UUID = Depends(get_current_user_id),
):
    """Proxies the metered USDA key, so it can't be an open relay."""
    results = await search_foods(query)
    return FoodSearchResponse(query=query, results=results)
