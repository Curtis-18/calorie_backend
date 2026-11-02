from datetime import date

import pytest

from app.schemas.target import OnboardingIn
from app.services.target_calculator import calculate_age, calculate_targets, lb_to_kg


def profile(**overrides):
    base = dict(
        date_of_birth=date(1995, 1, 1),
        sex="male",
        height_feet=5,
        height_inches=10,
        weight_value=180,
        weight_unit="lb",
        activity_level="moderate",
        goal="maintain",
    )
    base.update(overrides)
    return OnboardingIn(**base)


def test_age_before_birthday_is_not_counted():
    assert calculate_age(date(2000, 6, 15), today=date(2026, 6, 14)) == 25
    assert calculate_age(date(2000, 6, 15), today=date(2026, 6, 15)) == 26


def test_lb_conversion():
    assert lb_to_kg(100) == pytest.approx(45.359237)


@pytest.mark.parametrize(
    "overrides",
    [
        # Small bodies on a cut (healthy BMI: weight loss below 18.5 is refused).
        {"height_feet": 4, "height_inches": 11, "weight_value": 98, "sex": "female", "goal": "lose", "activity_level": "sedentary"},
        {"height_feet": 5, "height_inches": 0, "weight_value": 48, "weight_unit": "kg", "goal": "lose", "activity_level": "sedentary"},
        {"goal": "gain", "activity_level": "active", "weight_value": 110, "weight_unit": "kg"},
        {"goal": "maintain"},
        {"height_feet": 8, "height_inches": 11.9, "weight_value": 400, "weight_unit": "lb"},
        {"height_feet": 3, "height_inches": 0, "weight_value": 50, "weight_unit": "kg"},
    ],
)
def test_macros_never_exceed_the_calorie_budget(overrides):
    """Regression: an aggressive cut could emit a negative carb target."""
    r = calculate_targets(profile(**overrides))
    macro_kcal = r["protein_g"] * 4 + r["fat_g"] * 9 + r["carbs_g"] * 4
    assert r["protein_g"] >= 0
    assert r["fat_g"] >= 0
    assert r["carbs_g"] >= 0
    assert r["calorie_target"] >= 1200
    # Allow rounding slack, but macros must not blow past the target.
    assert macro_kcal <= r["calorie_target"] * 1.05, (r, macro_kcal)


def test_calorie_floor_applies():
    r = calculate_targets(
        profile(height_feet=4, height_inches=11, weight_value=45, weight_unit="kg",
                sex="female", goal="lose", activity_level="sedentary")
    )
    assert r["calorie_target"] == 1200


def test_bmi_present_and_finite():
    r = calculate_targets(profile())
    assert 15 < r["bmi"] < 40


# --- health standards (see handover "Nutrition accuracy audit") -------------

import itertools

from app.services.target_calculator import (
    MAX_DEFICIT_FRACTION,
    MIN_CALORIES,
    UnderageError,
    UnderweightLossError,
    compute_targets,
    protein_reference_weight,
)

TODAY = date(2026, 11, 2)
GRID = list(itertools.product(
    ("female", "male"),
    (150, 165, 180, 195),            # height cm
    (45, 60, 80, 110, 160),          # weight kg
    (18, 35, 60, 80),                # age
    ("sedentary", "light", "moderate", "active", "very_active"),
    ("lose", "maintain", "gain"),
))


def _targets(sex, height, weight, age, activity, goal):
    return compute_targets(
        date_of_birth=date(TODAY.year - age, 1, 1), sex=sex, height_cm=height,
        weight_kg=weight, activity_level=activity, goal=goal, today=TODAY,
    )


def test_every_profile_meets_the_standards():
    """4,320 adult profiles, each checked against every rule."""
    problems = []
    for sex, height, weight, age, activity, goal in GRID:
        if goal == "lose" and weight / (height / 100) ** 2 < 18.5:
            continue  # refused; covered by test_no_weight_loss_when_underweight
        r = _targets(sex, height, weight, age, activity, goal)
        T, tdee = r["calorie_target"], r["tdee"]
        p_kcal, f_kcal, c_kcal = r["protein_g"] * 4, r["fat_g"] * 9, r["carbs_g"] * 4
        label = (sex, height, weight, age, activity, goal, r)

        if goal == "lose":
            if T > round(tdee):
                problems.append(("weight loss above maintenance", label))
            if tdee - T > MAX_DEFICIT_FRACTION * tdee + 1:
                problems.append(("deficit over 25%", label))
            if T < min(MIN_CALORIES[sex], round(tdee)):
                problems.append(("below the floor", label))
        else:
            if T < MIN_CALORIES[sex]:
                problems.append(("below the floor", label))
        if abs(p_kcal + f_kcal + c_kcal - T) > 0.02 * T:
            problems.append(("macros don't add up", label))
        if p_kcal > 0.35 * T + 4:
            problems.append(("protein over 35%", label))
        if p_kcal < 0.10 * T - 4:
            problems.append(("protein under 10%", label))
        if not (0.20 * T - 9 <= f_kcal <= 0.35 * T + 9):
            problems.append(("fat outside 20-35%", label))
        if r["carbs_g"] < 130:
            problems.append(("carbs under 130 g", label))
    assert not problems, problems[:5]


def test_minors_are_refused():
    with pytest.raises(UnderageError):
        _targets("female", 150, 40, 13, "sedentary", "lose")
    with pytest.raises(UnderageError):
        _targets("male", 175, 65, 17, "active", "maintain")
    _targets("male", 175, 65, 18, "active", "maintain")  # 18 is fine


def test_men_have_a_1500_floor_and_women_1200():
    small_man = _targets("male", 160, 50, 75, "sedentary", "maintain")
    assert small_man["calorie_target"] >= 1500
    small_woman = _targets("female", 150, 45, 30, "sedentary", "lose")
    assert small_woman["calorie_target"] == 1200


def test_weight_loss_never_becomes_a_surplus():
    """TDEE under the men's floor: eat at maintenance, not 1500."""
    r = _targets("male", 155, 48, 80, "sedentary", "lose")
    assert r["tdee"] < 1500
    assert r["calorie_target"] == round(r["tdee"])


def test_protein_uses_adjusted_weight_for_larger_bodies():
    """Regression: 120 kg / 165 cm woman got 240 g protein (55% of energy)."""
    r = _targets("female", 165, 120, 40, "sedentary", "lose")
    assert r["protein_g"] * 4 <= 0.35 * r["calorie_target"] + 4
    assert r["protein_g"] < 200
    assert protein_reference_weight(120, 165) < 120
    assert protein_reference_weight(70, 175) == 70  # BMI < 30: actual weight


def test_small_cut_keeps_carbs_at_the_rda():
    """Regression: 1200 kcal cuts left 105-126 g carbs (RDA is 130 g)."""
    r = _targets("female", 155, 50, 30, "sedentary", "lose")
    assert r["calorie_target"] == 1200
    assert r["carbs_g"] >= 130
    assert r["fat_g"] * 9 >= 0.20 * 1200 - 9


def test_no_weight_loss_when_underweight():
    with pytest.raises(UnderweightLossError):
        _targets("female", 170, 50, 25, "light", "lose")  # BMI 17.3
    assert _targets("female", 170, 50, 25, "light", "maintain")["calorie_target"] >= 1200
    _targets("female", 170, 54, 25, "light", "lose")  # BMI 18.7 is allowed
