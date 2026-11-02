import asyncio
import logging
import re

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


# Ranking for picking one USDA entry to stand for a detected food. Ported
# from the Flutter client, where it lived while the client did its own
# lookups: prefer generic data types over branded products, and penalise
# entries whose extra words mark a different product ("apple juice" for
# "apple", "rice flour" for "rice").
_DATA_TYPE_RANK = {"Foundation": 0, "SR Legacy": 1, "Survey (FNDDS)": 2, "Branded": 3}
_PENALIZED_WORDS = {
    "oil", "powder", "extract", "dried", "juice", "sauce", "syrup", "flour",
    "concentrate", "flavored", "flavor", "seasoning", "dressing", "chips",
    "flakes", "paste", "butter", "dehydrated", "canned", "frozen", "candied",
    "imitation", "substitute",
}


def _words(text: str) -> set[str]:
    return {w for w in re.split(r"[\s,]+", text.lower()) if w}


def rank_best_match(results: list[FoodSearchResult], query: str) -> FoodSearchResult | None:
    """The result that best stands for [query], or None if none has calories."""
    candidates = [r for r in results if r.calories_per_100g is not None]
    if not candidates:
        return None
    query_words = _words(query)

    def score(item: FoodSearchResult) -> int:
        extra = _words(item.description) - query_words
        penalized = len(extra & _PENALIZED_WORDS)
        type_rank = _DATA_TYPE_RANK.get(item.data_type or "", 4)
        return penalized * 1000 + type_rank * 10 + len(extra)

    # min() keeps the first of equal scores, i.e. USDA's own relevance order.
    return min(candidates, key=score)


async def get_best_match(food_name: str) -> FoodSearchResult | None:
    return rank_best_match(await search_foods(food_name, page_size=20), food_name)


async def enrich_detected_foods(items: list[dict]) -> list[dict]:
    """Attach per-100 g macros to each {name, estimated_grams} from Gemini.

    Lookups run in parallel and one failure only leaves that item unmatched,
    so a single bad name can't sink the whole scan.
    """

    async def enrich(item: dict) -> dict:
        try:
            match = await get_best_match(item["name"])
        except Exception:  # noqa: BLE001 - leave this item unmatched
            log.exception("usda lookup failed for %r", item["name"])
            match = None
        return {
            **item,
            "matched": match is not None,
            "calories_per_100g": match.calories_per_100g if match else None,
            "protein_g_per_100g": match.protein_g_per_100g if match else None,
            "carbs_g_per_100g": match.carbs_g_per_100g if match else None,
            "fat_g_per_100g": match.fat_g_per_100g if match else None,
        }

    return list(await asyncio.gather(*(enrich(i) for i in items)))
