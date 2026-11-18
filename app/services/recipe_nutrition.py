"""A recipe's nutrition per serving, computed from its ingredients.

Always computed here from USDA values, never typed in by the author, so a
recipe's numbers can be explained ("from these 7 ingredients") and can't be
faked (roadmap P3.1). The rules are the same as everywhere else:

- An extra nutrient (fibre, sodium...) is reported only when *every*
  ingredient has a value for it. A missing value is unknown, not zero, and a
  partial sum would understate the recipe, so the key is left out.
- The basis is "ingredients" only when every ingredient came from USDA.
  Anything the author typed makes the recipe "manual", shown as estimated.
"""

from dataclasses import dataclass, field

from app.services.nutrients import NUTRIENT_KEYS

MIN_SERVINGS = 0.25
MAX_SERVINGS = 100


@dataclass(frozen=True)
class Ingredient:
    name: str
    grams: float
    source: str                      # 'usda' | 'manual'
    fdc_id: int | None
    calories_per_100g: float
    protein_g_per_100g: float
    carbs_g_per_100g: float
    fat_g_per_100g: float
    nutrients_per_100g: dict[str, float] = field(default_factory=dict)  # known extras only
    is_baseline: bool = False


@dataclass(frozen=True)
class PerServing:
    calories: int
    protein_g: float
    carbs_g: float
    fat_g: float
    nutrients: dict[str, float]
    basis: str


def compute_per_serving(ingredients: list[Ingredient], servings: float) -> PerServing:
    if not ingredients:
        raise ValueError("a recipe needs at least one ingredient")
    if not MIN_SERVINGS <= servings <= MAX_SERVINGS:
        raise ValueError("servings out of range")

    def total(attr: str) -> float:
        return sum(getattr(i, attr) * i.grams / 100 for i in ingredients)

    nutrients: dict[str, float] = {}
    for key in NUTRIENT_KEYS:
        if all(key in i.nutrients_per_100g for i in ingredients):
            amount = sum(i.nutrients_per_100g[key] * i.grams / 100 for i in ingredients) / servings
            nutrients[key] = round(amount, 1)

    return PerServing(
        calories=round(total("calories_per_100g") / servings),
        protein_g=round(total("protein_g_per_100g") / servings, 1),
        carbs_g=round(total("carbs_g_per_100g") / servings, 1),
        fat_g=round(total("fat_g_per_100g") / servings, 1),
        nutrients=nutrients,
        basis="ingredients" if all(i.source == "usda" for i in ingredients) else "manual",
    )


def scale(per_serving: dict, servings: float) -> dict:
    """The amounts for eating `servings` of a recipe (for a food-log entry)."""
    out = {
        "calories": round(per_serving["calories"] * servings),
        "protein_g": round(per_serving["protein_g"] * servings, 1),
        "carbs_g": round(per_serving["carbs_g"] * servings, 1),
        "fat_g": round(per_serving["fat_g"] * servings, 1),
    }
    out["nutrients"] = {k: round(v * servings, 1) for k, v in (per_serving.get("nutrients") or {}).items()}
    return out
