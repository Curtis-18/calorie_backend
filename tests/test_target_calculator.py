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
        {"weight_value": 95, "sex": "female", "goal": "lose", "activity_level": "sedentary"},
        {"weight_value": 40, "weight_unit": "kg", "goal": "lose", "activity_level": "sedentary"},
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
        profile(weight_value=40, weight_unit="kg", sex="female", goal="lose", activity_level="sedentary")
    )
    assert r["calorie_target"] == 1200


def test_bmi_present_and_finite():
    r = calculate_targets(profile())
    assert 15 < r["bmi"] < 40
