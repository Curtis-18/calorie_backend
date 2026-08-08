from fastapi import APIRouter
from app.models.food import FoodSearchResponse
from app.services.usda_service import search_foods

router = APIRouter(prefix="/foods", tags=["foods"])

@router.get("/search", response_model=FoodSearchResponse)
async def search(query: str):
    results = await search_foods(query)
    return FoodSearchResponse(query=query, results=results)