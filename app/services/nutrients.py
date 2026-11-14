"""The extra nutrients the app tracks beyond calories and macros.

One list, so the USDA reader, the stored amounts, the daily targets and the
API all agree on the keys. Rules (see handover "Micronutrients"):

- Amounts come from the USDA match, never from the photo AI.
- A food with no data for a nutrient is *unknown*, not zero: its key is simply
  absent, and the app says a day's total is based on the foods it could match.
- Targets are the US National Academies reference intakes for adults. They are
  general guidance, never a diagnosis: no deficiency alerts, no medical claims.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Nutrient:
    key: str  # as stored and sent, e.g. "iron_mg"
    unit: str  # USDA unitName
    usda_names: tuple[str, ...]  # in order of preference


NUTRIENTS = (
    Nutrient("fiber_g", "G", ("Fiber, total dietary",)),
    # USDA has renamed total sugars more than once across its data types.
    Nutrient("sugar_g", "G", ("Total Sugars", "Sugars, Total", "Sugars, total including NLEA", "Sugars, Total NLEA")),
    Nutrient("sodium_mg", "MG", ("Sodium, Na",)),
    Nutrient("iron_mg", "MG", ("Iron, Fe",)),
    Nutrient("calcium_mg", "MG", ("Calcium, Ca",)),
)
NUTRIENT_KEYS = tuple(n.key for n in NUTRIENTS)

# Fibre: Adequate Intake of 14 g per 1,000 kcal (Dietary Guidelines for Americans).
FIBER_G_PER_1000_KCAL = 14
# Sodium: the adult Chronic Disease Risk Reduction level. A limit, not a goal.
SODIUM_LIMIT_MG = 2300


def nutrient_targets(sex: str, age: int, calorie_target: int) -> dict:
    """Daily reference amounts for an adult. Sugar has none: USDA reports
    total sugars (fruit and milk included), and the guidance is about added
    sugar only, so a target here would mislead."""
    if sex == "female":
        iron = 18 if age <= 50 else 8
        calcium = 1200 if age >= 51 else 1000
    else:
        iron = 8
        calcium = 1200 if age >= 71 else 1000
    return {
        "fiber_g": round(FIBER_G_PER_1000_KCAL * calorie_target / 1000),
        "sodium_limit_mg": SODIUM_LIMIT_MG,
        "iron_mg": iron,
        "calcium_mg": calcium,
    }
