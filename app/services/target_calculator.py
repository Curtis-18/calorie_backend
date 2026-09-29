from datetime import date

from app.schemas.target import OnboardingIn

ACTIVITY_MULTIPLIERS = {
    "sedentary": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "active": 1.725,
    "very_active": 1.9,
}

GOAL_ADJUSTMENT_KCAL = {
    "lose": -500,
    "maintain": 0,
    "gain": 500,
}

MIN_SAFE_CALORIE_TARGET = 1200  # floor, in case a low weight/height combo produces something absurd

# Heuristics, not clinical guidance: protein scaled by bodyweight and goal
# (higher on a cut, to protect muscle), fat as a percent of total calories,
# carbs fill whatever's left.
PROTEIN_G_PER_KG = {
    "lose": 2.0,
    "maintain": 1.6,
    "gain": 1.8,
}

FAT_PERCENT_OF_CALORIES = {
    "lose": 0.25,
    "maintain": 0.30,
    "gain": 0.25,
}

MIN_CARBS_G = 50  # floor, avoid a near-zero or negative carb target on an aggressive deficit

# On a 1200 kcal floor the protein and fat floors alone can exceed the budget,
# which produced a negative carb allowance. Cap protein and fat so the three
# macros always sum to something at or above the target.
MAX_PROTEIN_KG = 2.2
MIN_PROTEIN_KG = 0.8
MAX_FAT_PERCENT = 0.35


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


def calculate_macro_targets(weight_kg: float, calorie_target: int, goal: str) -> dict:
    protein_per_kg = min(max(PROTEIN_G_PER_KG[goal], MIN_PROTEIN_KG), MAX_PROTEIN_KG)
    protein_g = round(weight_kg * protein_per_kg)

    # Never let fat claim more than MAX_FAT_PERCENT of the budget, otherwise
    # there is no room left for carbs and the totals stop adding up.
    fat_g = round((calorie_target * min(FAT_PERCENT_OF_CALORIES[goal], MAX_FAT_PERCENT)) / 9)

    remaining_kcal = calorie_target - (protein_g * 4) - (fat_g * 9)
    carbs_g = max(MIN_CARBS_G, round(remaining_kcal / 4))

    # If protein + fat still overshoot the floor, trim fat back to fit.
    overflow = (protein_g * 4 + fat_g * 9 + carbs_g * 4) - calorie_target
    if overflow > 0:
        trim_g = round(overflow / 9)
        fat_g = max(0, fat_g - trim_g)
        remaining_kcal = calorie_target - (protein_g * 4) - (fat_g * 9)
        carbs_g = max(MIN_CARBS_G, round(remaining_kcal / 4))

    return {"protein_g": protein_g, "fat_g": fat_g, "carbs_g": carbs_g}


def calculate_targets(data: OnboardingIn) -> dict:
    age = calculate_age(data.date_of_birth)
    height_cm = feet_inches_to_cm(data.height_feet, data.height_inches)
    weight_kg = data.weight_value if data.weight_unit == "kg" else lb_to_kg(data.weight_value)

    bmr = calculate_bmr(weight_kg, height_cm, age, data.sex)
    tdee = bmr * ACTIVITY_MULTIPLIERS[data.activity_level]
    calorie_target = max(round(tdee + GOAL_ADJUSTMENT_KCAL[data.goal]), MIN_SAFE_CALORIE_TARGET)
    bmi = weight_kg / ((height_cm / 100) ** 2) if height_cm else 0.0
    macros = calculate_macro_targets(weight_kg, calorie_target, data.goal)

    return {
        "height_cm": round(height_cm, 1),
        "weight_kg": round(weight_kg, 1),
        "bmr": round(bmr, 1),
        "tdee": round(tdee, 1),
        "calorie_target": calorie_target,
        "bmi": round(bmi, 1),
        **macros,
    }
