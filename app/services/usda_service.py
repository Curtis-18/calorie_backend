import logging

import httpx

from app.core.config import settings
from app.models.food import FoodSearchResult

log = logging.getLogger("calorie_backend")

# USDA spells these inconsistently across data types; match the variants that
# actually show up so a result doesn't silently come back with null macros.
_NUTRIENT_ALIASES = {
    "calories": {"Energy"},
    "protein_g": {"Protein"},
    "fat_g": {"Total lipid (fat)", "Total lipid (fat) (NLEA)"},
    "carbs_g": {"Carbohydrate, by difference", "Carbohydrate, by difference (NLEA)"},
}


def _extract_nutrients(food: dict) -> dict:
    nutrients: dict = {key: None for key in _NUTRIENT_ALIASES}
    seen: set[str] = set()

    for nutrient in food.get("foodNutrients") or []:
        name = nutrient.get("nutrientName")
        unit = nutrient.get("unitName")
        value = nutrient.get("value")
        if not name or value is None:
            continue

        if name in _NUTRIENT_ALIASES["calories"] and unit == "KCAL" and "calories" not in seen:
            nutrients["calories"] = float(value)
            seen.add("calories")
            continue

        for key, aliases in _NUTRIENT_ALIASES.items():
            if key == "calories" or key in seen:
                continue
            if name in aliases:
                nutrients[key] = float(value)
                seen.add(key)
                break

    return nutrients


async def search_foods(query: str, page_size: int = 10) -> list[FoodSearchResult]:
    query = query.strip()
    if not query:
        return []

    params = {
        "api_key": settings.usda_api_key,
        "query": query,
        "pageSize": page_size,
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            f"{settings.usda_base_url}/foods/search",
            params=params,
        )
        if response.status_code >= 400:
            log.error("usda error %s: %s", response.status_code, response.text[:500])
        response.raise_for_status()
        data = response.json()

    results = []
    for food in data.get("foods") or []:
        fdc_id = food.get("fdcId")
        description = food.get("description")
        if fdc_id is None or not description:
            continue
        nutrients = _extract_nutrients(food)
        # _extract_nutrients keys (calories, protein_g...) differ from the
        # model's field names. Splatting them in directly failed validation on
        # every result, so this endpoint 500'd for any non-empty search.
        results.append(
            FoodSearchResult(
                fdc_id=fdc_id,
                description=description,
                data_type=food.get("dataType"),
                calories_per_100g=nutrients["calories"],
                protein_g_per_100g=nutrients["protein_g"],
                carbs_g_per_100g=nutrients["carbs_g"],
                fat_g_per_100g=nutrients["fat_g"],
            )
        )

    return results


async def get_best_match(food_name: str) -> FoodSearchResult | None:
    matches = await search_foods(food_name)
    return matches[0] if matches else None
