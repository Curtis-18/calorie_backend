import httpx
from app.core.config import settings
from app.models.food import FoodSearchResult

async def search_foods(query: str) -> list[FoodSearchResult]:
    params = {
        "api_key": settings.usda_api_key,
        "query": query,
        "pageSize": 10,
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            f"{settings.usda_base_url}/foods/search",
            params=params,
        )
        response.raise_for_status()
        data = response.json()

    results = []
    for food in data.get("foods", []):
        nutrients = {
            "calories_per_100g": None,
            "protein_g_per_100g": None,
            "carbs_g_per_100g": None,
            "fat_g_per_100g": None,
        }

        for nutrient in food.get("foodNutrients", []):
            name = nutrient.get("nutrientName")
            if name == "Energy" and nutrient.get("unitName") == "KCAL":
                nutrients["calories_per_100g"] = nutrient.get("value")
            elif name == "Protein":
                nutrients["protein_g_per_100g"] = nutrient.get("value")
            elif name == "Total lipid (fat)":
                nutrients["fat_g_per_100g"] = nutrient.get("value")
            elif name == "Carbohydrate, by difference":
                nutrients["carbs_g_per_100g"] = nutrient.get("value")

        results.append(
            FoodSearchResult(
                fdc_id=food["fdcId"],
                description=food["description"],
                **nutrients,
            )
        )

    return results


async def get_best_match(food_name: str) -> FoodSearchResult | None:
    matches = await search_foods(food_name)
    return matches[0] if matches else None