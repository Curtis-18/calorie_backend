import asyncio
import logging
import re

import httpx

from app.core.config import settings
from app.models.food import FoodSearchResult
from app.services.nutrients import NUTRIENTS

log = logging.getLogger("calorie_backend")

# Where each value can come from, in order of preference. USDA labels these
# differently across data types, and a value we don't recognise silently
# becomes None. In particular many Foundation foods (USDA's newest analytical
# data) report energy only as "Energy (Atwater Specific/General Factors)" with
# no plain "Energy", so they were dropped from search and photo matching.
# Specific factors come before General because SR Legacy's "Energy" is
# itself calculated with specific factors, which keeps sources consistent.
_NUTRIENT_SOURCES: dict[str, list[tuple[str, str | None]]] = {
    "calories": [
        ("Energy", "KCAL"),
        ("Energy (Atwater Specific Factors)", "KCAL"),
        ("Energy (Atwater General Factors)", "KCAL"),
    ],
    "protein_g": [("Protein", None)],
    "fat_g": [("Total lipid (fat)", None), ("Total lipid (fat) (NLEA)", None)],
    "carbs_g": [
        ("Carbohydrate, by difference", None),
        ("Carbohydrate, by difference (NLEA)", None),
        ("Carbohydrate, by summation", None),
    ],
}


def _values_by_name(food: dict) -> dict[tuple[str, str], float]:
    found: dict[tuple[str, str], float] = {}
    for nutrient in food.get("foodNutrients") or []:
        name = nutrient.get("nutrientName")
        value = nutrient.get("value")
        if not name or value is None:
            continue
        found.setdefault((name, (nutrient.get("unitName") or "").upper()), float(value))
    return found


def _pick(found: dict[tuple[str, str], float], sources: list[tuple[str, str | None]]) -> float | None:
    for name, unit in sources:
        for (found_name, found_unit), value in found.items():
            if found_name == name and (unit is None or found_unit == unit):
                return value
    return None


def _not_negative(value: float | None) -> float | None:
    """USDA's "carbohydrate, by difference" is calculated and comes out slightly
    below zero for some foods (-0.4 g per 100 g). A negative amount cannot be
    logged (the save is refused), so it is read as none. Unknown stays unknown."""
    return None if value is None else max(value, 0.0)


def _extract_nutrients(food: dict) -> dict:
    found = _values_by_name(food)
    return {key: _not_negative(_pick(found, sources)) for key, sources in _NUTRIENT_SOURCES.items()}


def _extract_extras(food: dict) -> dict:
    """Fibre, sugar, sodium, iron and calcium per 100 g, keyed as the API
    sends them. The unit is checked, so a value USDA reports in an unexpected
    unit is left unknown rather than read as 1000x off."""
    found = _values_by_name(food)
    return {
        f"{n.key}_per_100g": _not_negative(_pick(found, [(name, n.unit) for name in n.usda_names]))
        for n in NUTRIENTS
    }


def _alcohol_g(food: dict) -> float:
    return _pick(_values_by_name(food), [("Alcohol, ethyl", None)]) or 0.0


def is_plausible(nutrients: dict, alcohol_g: float = 0.0) -> bool:
    """Whether stated calories roughly agree with the macros (Atwater 4/4/9/7).

    Branded entries are manufacturer-submitted and some are plainly broken
    (an olive oil at 0 kcal per 100 g). Generous bounds, so fibre, sugar
    alcohols and specific-vs-general Atwater factors don't trip it.
    """
    calories = nutrients.get("calories")
    if calories is None:
        return True  # nothing to check; callers already skip these
    expected = (
        4 * (nutrients.get("protein_g") or 0)
        + 4 * (nutrients.get("carbs_g") or 0)
        + 9 * (nutrients.get("fat_g") or 0)
        + 7 * alcohol_g
    )
    if abs(calories - expected) <= 60:
        return True
    if calories <= 0 or expected <= 0:
        return False
    return 0.35 <= calories / expected <= 1.6


def _result_from_food(food: dict) -> FoodSearchResult | None:
    """One USDA search hit as our result, or None when it can't be used."""
    fdc_id = food.get("fdcId")
    description = food.get("description")
    if fdc_id is None or not description:
        return None
    nutrients = _extract_nutrients(food)
    if food.get("dataType") == "Branded" and not is_plausible(nutrients, _alcohol_g(food)):
        log.info("skipping implausible branded food %s: %s", fdc_id, nutrients)
        return None
    # _extract_nutrients keys (calories, protein_g...) differ from the
    # model's field names. Splatting them in directly failed validation on
    # every result, so this endpoint 500'd for any non-empty search.
    return FoodSearchResult(
        fdc_id=fdc_id,
        description=description,
        data_type=food.get("dataType"),
        calories_per_100g=nutrients["calories"],
        protein_g_per_100g=nutrients["protein_g"],
        carbs_g_per_100g=nutrients["carbs_g"],
        fat_g_per_100g=nutrients["fat_g"],
        **_extract_extras(food),
    )


async def search_foods(query: str, page_size: int = 10) -> list[FoodSearchResult]:
    query = query.strip()
    if not query:
        return []

    params = {
        "query": query,
        "pageSize": page_size,
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            f"{settings.usda_base_url}/foods/search",
            params=params,
            # In a header, not `?api_key=`: raise_for_status() puts the full
            # URL in its message, which the callers log, key included.
            headers={"X-Api-Key": settings.usda_api_key},
        )
        if response.status_code >= 400:
            log.error("usda error %s: %s", response.status_code, response.text[:500])
        response.raise_for_status()
        data = response.json()

    results = []
    for food in data.get("foods") or []:
        result = _result_from_food(food)
        if result is not None:
            results.append(result)

    return results


async def get_foods_by_ids(fdc_ids: list[int]) -> dict[int, FoodSearchResult]:
    """USDA foods by id, in one request, keyed by id. An id USDA doesn't know,
    or whose values can't be used, is simply missing from the answer. The
    abridged format carries nutrients in the same shape as search results, so
    the same reader is used."""
    ids = sorted(set(fdc_ids))
    if not ids:
        return {}
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            f"{settings.usda_base_url}/foods",
            params={"fdcIds": ",".join(str(i) for i in ids), "format": "abridged"},
            headers={"X-Api-Key": settings.usda_api_key},
        )
        if response.status_code >= 400:
            log.error("usda error %s: %s", response.status_code, response.text[:500])
        response.raise_for_status()
        foods = response.json()
    out: dict[int, FoodSearchResult] = {}
    for food in foods if isinstance(foods, list) else []:
        result = _result_from_food(food)
        if result is not None:
            out[result.fdc_id] = result
    return out


def normalize_barcode(code: str) -> str | None:
    """Digits only, 8 to 14 long (EAN-8, UPC-A, EAN-13, GTIN-14), else None."""
    code = code.strip()
    if not code.isascii() or not code.isdigit() or not 8 <= len(code) <= 14:
        return None
    return code


def _same_barcode(a: str, b: str) -> bool:
    # A UPC-A is an EAN-13 with a leading zero, and USDA stores either form.
    return a.lstrip("0") == b.lstrip("0")


def barcode_forms(code: str) -> list[str]:
    """The spellings USDA might have stored for one barcode.

    Checked live: USDA matches the stored digits exactly, and stores some
    products zero-padded to 14 digits ("00016000275287") and others as printed,
    so a scanned 12-digit UPC finds nothing unless it is padded the same way.
    """
    forms = [code]
    for width in (12, 13, 14):
        padded = code.lstrip("0").zfill(width)
        if len(padded) == width and padded not in forms:
            forms.append(padded)
    return forms


async def lookup_barcode(code: str) -> FoodSearchResult | None:
    """The branded USDA food with this exact barcode, or None.

    USDA indexes the barcode (`gtinUpc`) for text search, but a search for
    digits can also hit other fields, so only an entry whose own barcode
    equals the scanned one is returned.
    """
    async with httpx.AsyncClient(timeout=15.0) as client:

        async def search(form: str) -> list[dict]:
            response = await client.get(
                f"{settings.usda_base_url}/foods/search",
                params={"query": form, "dataType": "Branded", "pageSize": 25},
                headers={"X-Api-Key": settings.usda_api_key},
            )
            if response.status_code >= 400:
                log.error("usda error %s: %s", response.status_code, response.text[:500])
            response.raise_for_status()
            return response.json().get("foods") or []

        batches = await asyncio.gather(*(search(form) for form in barcode_forms(code)))

    for foods in batches:
        for food in foods:
            if _same_barcode(str(food.get("gtinUpc") or ""), code):
                result = _result_from_food(food)
                if result is not None:
                    return result
    return None


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
            "matched_description": match.description if match else None,
            "matched_fdc_id": match.fdc_id if match else None,
            "calories_per_100g": match.calories_per_100g if match else None,
            "protein_g_per_100g": match.protein_g_per_100g if match else None,
            "carbs_g_per_100g": match.carbs_g_per_100g if match else None,
            "fat_g_per_100g": match.fat_g_per_100g if match else None,
            **{
                f"{n.key}_per_100g": getattr(match, f"{n.key}_per_100g") if match else None
                for n in NUTRIENTS
            },
        }

    return list(await asyncio.gather(*(enrich(i) for i in items)))
