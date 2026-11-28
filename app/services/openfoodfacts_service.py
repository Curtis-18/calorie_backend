"""Open Food Facts as a second source for barcodes.

USDA Branded is mostly US products, so a European or regional barcode often
misses. Open Food Facts (a community database, licensed ODbL: the data may be
used commercially if it is credited, which the app does on the barcode result)
covers much of the rest of the world.

Rules, the same as for USDA:
- Per 100 g (per 100 ml for drinks, see `_per_unit`), in the same `FoodSearchResult` shape. It has no FDC id, so
  `fdc_id` is 0 and `data_type` is "Open Food Facts".
- A value it doesn't have is unknown, never zero. Open Food Facts stores
  minerals in grams, so they are converted to milligrams.
- A product without a name or calories, or whose calories disagree with its
  own macros (community data has typos), is not used.
- Only the barcode is sent. No person or account detail, and a generic
  User-Agent (the site asks API users to identify the app).
"""

import logging

import httpx

from app.core.config import settings
from app.models.food import FoodSearchResult
from app.services.usda_service import is_plausible

log = logging.getLogger("calorie_backend")

DATA_TYPE = "Open Food Facts"
_FIELDS = "product_name,brands,nutriments,product_quantity_unit"
_USER_AGENT = "NuStreak-Backend/1.0"


def _num(nutriments: dict, key: str) -> float | None:
    value = nutriments.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if value >= 0 else None


def _milligrams(nutriments: dict, key: str) -> float | None:
    grams = _num(nutriments, key)
    return None if grams is None else round(grams * 1000, 3)


def _per_unit(product: dict) -> str:
    """Open Food Facts' "_100g" values follow the label, which is per 100 ml for
    a product sold by volume (a 330 ml cola: "product_quantity_unit": "ml",
    28 Nov 2026). Anything else, or no unit, is per 100 g."""
    unit = str(product.get("product_quantity_unit") or "").strip().lower()
    return "ml" if unit == "ml" else "g"


def _result_from_product(product: dict) -> FoodSearchResult | None:
    name = str(product.get("product_name") or "").strip()
    if not name:
        return None
    nutriments = product.get("nutriments") or {}
    calories = _num(nutriments, "energy-kcal_100g")
    if calories is None:
        kilojoules = _num(nutriments, "energy_100g")
        calories = round(kilojoules / 4.184, 1) if kilojoules is not None else None
    if calories is None:
        return None
    protein = _num(nutriments, "proteins_100g")
    carbs = _num(nutriments, "carbohydrates_100g")
    fat = _num(nutriments, "fat_100g")
    if not is_plausible({"calories": calories, "protein_g": protein, "carbs_g": carbs, "fat_g": fat}):
        log.info("skipping implausible Open Food Facts product: %s kcal", calories)
        return None
    brand = str(product.get("brands") or "").split(",")[0].strip()
    description = f"{brand} {name}" if brand and brand.lower() not in name.lower() else name
    return FoodSearchResult(
        fdc_id=0,
        description=description[:200],
        data_type=DATA_TYPE,
        calories_per_100g=calories,
        protein_g_per_100g=protein,
        carbs_g_per_100g=carbs,
        fat_g_per_100g=fat,
        fiber_g_per_100g=_num(nutriments, "fiber_100g"),
        sugar_g_per_100g=_num(nutriments, "sugars_100g"),
        sodium_mg_per_100g=_milligrams(nutriments, "sodium_100g"),
        iron_mg_per_100g=_milligrams(nutriments, "iron_100g"),
        calcium_mg_per_100g=_milligrams(nutriments, "calcium_100g"),
        per_unit=_per_unit(product),
    )


async def lookup_barcode(code: str) -> FoodSearchResult | None:
    """The product with this barcode, or None when Open Food Facts has none
    or can't be used. Never raises for an upstream failure: this is a fallback,
    so an outage here must not turn a plain "not found" into an error."""
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(
                f"{settings.off_base_url}/product/{code}.json",
                params={"fields": _FIELDS},
                headers={"User-Agent": _USER_AGENT},
            )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError):
        log.warning("open food facts barcode lookup failed", exc_info=True)
        return None
    if not isinstance(body, dict) or body.get("status") != 1:
        return None
    product = body.get("product")
    return _result_from_product(product) if isinstance(product, dict) else None
