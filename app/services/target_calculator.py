"""Daily calorie and macro targets.

Health basis (see handover "Nutrition accuracy audit"):
- BMR: Mifflin-St Jeor, the most reliable predictive equation in healthy
  adults (Frankenfield et al., J Am Diet Assoc 2005), x standard activity
  multipliers for TDEE. Adults only: the equation isn't for children, and the
  AAP advises against calorie counting for adolescents.
- Weight loss: a moderate deficit (500 kcal, at most 25% of TDEE), never
  below 1200 kcal (women) / 1500 kcal (men), the usual floor without medical
  supervision, and never above maintenance.
- Macros inside the National Academies AMDR: protein 10-35%, fat 20-35%,
  carbohydrate aiming for at least the 130 g/day RDA.
- Protein per kg follows sports-nutrition guidance (ISSN), scaled from an
  *adjusted* body weight at BMI >= 30 so it doesn't balloon for larger
  bodies (it was 55% of calories for a 120 kg woman).
- No weight-loss targets below BMI 18.5.
"""

from datetime import date

from app.schemas.target import OnboardingIn

MIN_AGE = 18

ACTIVITY_MULTIPLIERS = {
    "sedentary": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "active": 1.725,
    "very_active": 1.9,
}

# Goal adjustment: a fixed amount, capped as a share of TDEE so small, less
# active people get a proportionate change rather than a 30% cut.
DEFICIT_KCAL = 500
MAX_DEFICIT_FRACTION = 0.25
SURPLUS_KCAL = 500
MAX_SURPLUS_FRACTION = 0.20

MIN_CALORIES = {"female": 1200, "male": 1500}

PROTEIN_G_PER_KG = {"lose": 2.0, "maintain": 1.6, "gain": 1.8}
MIN_PROTEIN_G_PER_KG = 1.2  # floor when making room for carbohydrate
MAX_PROTEIN_FRACTION = 0.35  # AMDR upper bound

FAT_FRACTION = {"lose": 0.25, "maintain": 0.30, "gain": 0.25}
MIN_FAT_FRACTION = 0.20  # AMDR lower bound

MIN_CARBS_G = 130  # RDA; met whenever the budget allows
ABSOLUTE_MIN_CARBS_G = 50

# Protein reference weight above BMI 30: ideal weight (BMI 22.5) plus a
# quarter of the excess, the usual "adjusted body weight" convention.
OBESE_BMI = 30
IDEAL_BMI = 22.5
ADJUSTED_EXCESS_FRACTION = 0.25


UNDERWEIGHT_BMI = 18.5
MIN_PROTEIN_FRACTION = 0.10  # AMDR lower bound


class UnderageError(ValueError):
    """Targets are only calculated for adults."""


class UnderweightLossError(ValueError):
    """A weight-loss goal for someone already below a healthy BMI."""


def feet_inches_to_cm(feet: int, inches: float) -> float:
    return (feet * 12 + inches) * 2.54


def lb_to_kg(lb: float) -> float:
    return lb * 0.45359237


def calculate_bmr(weight_kg: float, height_cm: float, age: int, sex: str) -> float:
    base = 10 * weight_kg + 6.25 * height_cm - 5 * age
    return base + 5 if sex == "male" else base - 161


def calculate_age(dob: date, today: date | None = None) -> int:
    today = today or date.today()
    years = today.year - dob.year
    had_birthday_this_year = (today.month, today.day) >= (dob.month, dob.day)
    return years if had_birthday_this_year else years - 1


def protein_reference_weight(weight_kg: float, height_cm: float) -> float:
    """Actual weight, or adjusted body weight at BMI >= 30."""
    height_m = height_cm / 100
    bmi = weight_kg / height_m**2
    if bmi < OBESE_BMI:
        return weight_kg
    ideal = IDEAL_BMI * height_m**2
    return ideal + ADJUSTED_EXCESS_FRACTION * (weight_kg - ideal)


def calorie_target_for(tdee: float, goal: str, sex: str) -> int:
    floor = MIN_CALORIES[sex]
    if goal == "lose":
        deficit = min(DEFICIT_KCAL, MAX_DEFICIT_FRACTION * tdee)
        # Never below the floor, and never above maintenance: for someone
        # whose TDEE is already under the floor, that means "eat at
        # maintenance", not a surplus labelled weight loss.
        return round(min(tdee, max(tdee - deficit, floor)))
    if goal == "gain":
        surplus = min(SURPLUS_KCAL, MAX_SURPLUS_FRACTION * tdee)
        return round(max(tdee + surplus, floor))
    return round(max(tdee, floor))


def calculate_macro_targets(
    calorie_target: int, goal: str, weight_kg: float, height_cm: float
) -> dict:
    """Protein, fat and carbs (g) that add up to the calorie target.

    Order of priority: protein (bodyweight-based, capped at 35% of energy),
    fat (a share of energy), then carbohydrate takes the rest. If that leaves
    under 130 g of carbohydrate, fat is trimmed toward 20% and then protein
    toward 1.2 g/kg to make room.
    """
    ref_kg = protein_reference_weight(weight_kg, height_cm)
    protein_g = min(ref_kg * PROTEIN_G_PER_KG[goal], MAX_PROTEIN_FRACTION * calorie_target / 4)
    protein_g = max(protein_g, MIN_PROTEIN_FRACTION * calorie_target / 4)
    fat_g = FAT_FRACTION[goal] * calorie_target / 9

    def carbs_left() -> float:
        return (calorie_target - protein_g * 4 - fat_g * 9) / 4

    shortfall_kcal = (MIN_CARBS_G - carbs_left()) * 4
    if shortfall_kcal > 0:
        min_fat_g = MIN_FAT_FRACTION * calorie_target / 9
        trim = min(shortfall_kcal, (fat_g - min_fat_g) * 9)
        fat_g -= max(trim, 0) / 9
        shortfall_kcal = (MIN_CARBS_G - carbs_left()) * 4
    min_protein_g = max(
        min(ref_kg * MIN_PROTEIN_G_PER_KG, protein_g),
        MIN_PROTEIN_FRACTION * calorie_target / 4,
    )
    if shortfall_kcal > 0:
        trim = min(shortfall_kcal, (protein_g - min_protein_g) * 4)
        protein_g -= max(trim, 0) / 4

    protein = round(protein_g)
    fat = round(fat_g)
    carbs = round((calorie_target - protein * 4 - fat * 9) / 4)
    # Rounding can leave carbohydrate a gram or two short of the RDA: move
    # grams from protein (same 4 kcal/g) while protein stays above its floor.
    while carbs < MIN_CARBS_G and protein - 1 >= min_protein_g:
        protein -= 1
        carbs += 1
    carbs = max(ABSOLUTE_MIN_CARBS_G, carbs)
    return {"protein_g": protein, "fat_g": fat, "carbs_g": carbs}


def compute_targets(
    *,
    date_of_birth: date,
    sex: str,
    height_cm: float,
    weight_kg: float,
    activity_level: str,
    goal: str,
    today: date | None = None,
) -> dict:
    age = calculate_age(date_of_birth, today)
    if age < MIN_AGE:
        raise UnderageError(f"Targets are for adults ({MIN_AGE}+).")

    bmi = weight_kg / ((height_cm / 100) ** 2) if height_cm else 0.0
    if goal == "lose" and bmi < UNDERWEIGHT_BMI:
        raise UnderweightLossError("Weight loss isn't offered below a healthy BMI.")

    bmr = calculate_bmr(weight_kg, height_cm, age, sex)
    tdee = bmr * ACTIVITY_MULTIPLIERS[activity_level]
    calorie_target = calorie_target_for(tdee, goal, sex)
    macros = calculate_macro_targets(calorie_target, goal, weight_kg, height_cm)

    return {
        "height_cm": round(height_cm, 1),
        "weight_kg": round(weight_kg, 1),
        "bmr": round(bmr, 1),
        "tdee": round(tdee, 1),
        "calorie_target": calorie_target,
        "bmi": round(bmi, 1),
        **macros,
    }


def calculate_targets(data: OnboardingIn, today: date | None = None) -> dict:
    """Targets from the onboarding form (imperial or metric input)."""
    return compute_targets(
        date_of_birth=data.date_of_birth,
        sex=data.sex,
        height_cm=feet_inches_to_cm(data.height_feet, data.height_inches),
        weight_kg=data.weight_value if data.weight_unit == "kg" else lb_to_kg(data.weight_value),
        activity_level=data.activity_level,
        goal=data.goal,
        today=today,
    )
