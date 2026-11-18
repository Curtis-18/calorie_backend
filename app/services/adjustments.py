"""The one-tap extras on the photo review screen: hidden oil, butter, dressing...

Photos can't show what went into the pan. Each extra here adds a known amount
of one food as its own entry, so it can be seen, edited and removed like any
other.

No nutrition number is typed in this file. Each extra names a USDA search, and
the per-100 g values come from USDA itself (the same ranking as photo
matching), resolved once and remembered. A result whose calories fall outside
a sanity range for that kind of food is dropped, so a wrong match can never
silently put a wrong number on someone's log.
"""

import asyncio
import logging
from dataclasses import dataclass, field

from app.services.nutrients import NUTRIENTS
from app.services.usda_service import get_best_match

log = logging.getLogger("calorie_backend")


@dataclass(frozen=True)
class Extra:
    id: str
    label: str            # the chip text
    entry_name: str       # the name of the entry that gets added
    query: str            # USDA search for the food being added
    grams: float          # a typical amount
    kcal_range: tuple[float, float]   # sanity bounds per 100 g
    # Offered when any photographed food has one of these. "any" = always.
    preparations: tuple[str, ...] = ()
    kinds: tuple[str, ...] = ()


# Typical amounts are household measures (a tablespoon of oil is about 14 g).
EXTRAS: tuple[Extra, ...] = (
    Extra("oil", "+ Cooking oil", "Cooking oil, 1 tbsp (added)", "Oil, vegetable, soybean, refined", 14,
          (800, 920), preparations=("fried", "sauteed", "grilled", "baked")),
    Extra("butter", "+ Butter", "Butter, 1 tbsp (added)", "Butter, salted", 14,
          (650, 800), preparations=("fried", "sauteed", "grilled", "baked", "boiled")),
    Extra("dressing", "+ Creamy dressing", "Creamy dressing, 2 tbsp (added)", "Salad dressing, ranch dressing, regular", 30,
          (300, 600), kinds=("salad",)),
    Extra("cheese", "+ Cheese on top", "Cheese, 1 slice (added)", "Cheese, cheddar", 28,
          (320, 460), kinds=("main",)),
    Extra("sugar", "+ Sugar", "Sugar, 1 tsp (added)", "Sugars, granulated", 4,
          (360, 420), kinds=("drink",)),
)

# "Restaurant portion" scales the photographed foods instead of adding one.
# The factor is an unverified placeholder: shown as an estimate in the app, and
# to be replaced by a sourced number (roadmap P1.1).
RESTAURANT_FACTOR = 1.25

_cache: list[dict] | None = None
_lock = asyncio.Lock()


def _within(extra: Extra, kcal: float | None) -> bool:
    return kcal is not None and extra.kcal_range[0] <= kcal <= extra.kcal_range[1]


async def _resolve(extra: Extra) -> dict | None:
    try:
        match = await get_best_match(extra.query)
    except Exception:  # noqa: BLE001
        log.exception("adjustment lookup failed for %s", extra.id)
        return None
    if match is None or not _within(extra, match.calories_per_100g):
        log.warning("adjustment %s dropped: no plausible USDA match (%s)", extra.id, match and match.description)
        return None
    return {
        "id": extra.id,
        "kind": "add",
        "label": extra.label,
        "entry_name": extra.entry_name,
        "grams": extra.grams,
        "matched_description": match.description,
        "matched_fdc_id": match.fdc_id,
        "calories_per_100g": match.calories_per_100g,
        "protein_g_per_100g": match.protein_g_per_100g,
        "carbs_g_per_100g": match.carbs_g_per_100g,
        "fat_g_per_100g": match.fat_g_per_100g,
        **{f"{n.key}_per_100g": getattr(match, f"{n.key}_per_100g") for n in NUTRIENTS},
        "preparations": list(extra.preparations),
        "kinds": list(extra.kinds),
    }


async def list_adjustments() -> list[dict]:
    """The extras with USDA numbers. Resolved on first use and then remembered;
    a failed lookup is retried next time rather than remembered as missing."""
    global _cache
    if _cache is not None:
        return _cache
    async with _lock:
        if _cache is not None:
            return _cache
        resolved = await asyncio.gather(*(_resolve(e) for e in EXTRAS))
        found = [r for r in resolved if r is not None]
        scale = {
            "id": "restaurant",
            "kind": "scale",
            "label": "Restaurant portion",
            "factor": RESTAURANT_FACTOR,
            "preparations": [],
            "kinds": [],
            "always": True,
        }
        result = [*found, scale]
        if len(found) == len(EXTRAS):
            _cache = result  # only a complete answer is remembered
        return result


def reset_cache() -> None:
    global _cache
    _cache = None
