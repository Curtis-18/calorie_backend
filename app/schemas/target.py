from typing import Literal
from pydantic import BaseModel, Field, model_validator
from datetime import date

# The same limits as a weigh-in (services/weight_service.py), with a little
# slack for kg/lb rounding in the app.
MIN_WEIGHT_KG = 19.5
MAX_WEIGHT_KG = 400.5
EARLIEST_BIRTH_YEAR = 1900


class OnboardingIn(BaseModel):
    date_of_birth: date
    sex: Literal["male", "female"]
    height_feet: int = Field(ge=3, le=8)
    height_inches: float = Field(ge=0, lt=12, default=0, allow_inf_nan=False)
    weight_value: float = Field(gt=0, allow_inf_nan=False)
    weight_unit: Literal["kg", "lb"]
    activity_level: Literal["sedentary", "light", "moderate", "active", "very_active"]
    goal: Literal["lose", "maintain", "gain"]

    @model_validator(mode="after")
    def _plausible(self):
        # Unbounded, a weight of 1e300 or a birth year of 1 produced infinite
        # or negative targets and a 500 (or nonsense saved to the profile).
        kg = self.weight_value if self.weight_unit == "kg" else self.weight_value * 0.45359237
        if not MIN_WEIGHT_KG <= kg <= MAX_WEIGHT_KG:
            raise ValueError("Enter a weight between 20 and 400 kg.")
        if self.date_of_birth.year < EARLIEST_BIRTH_YEAR:
            raise ValueError("Check your date of birth.")
        return self


class TargetOut(BaseModel):
    # The onboarding answers, so a fresh install or new browser can rebuild the
    # whole profile from the server. Previously only the computed numbers came
    # back and the client had nothing to restore from but its own cache.
    date_of_birth: date | None = None
    sex: Literal["male", "female"] | None = None
    activity_level: Literal["sedentary", "light", "moderate", "active", "very_active"] | None = None
    goal: Literal["lose", "maintain", "gain"] | None = None

    height_cm: float
    weight_kg: float
    bmr: float
    tdee: float
    calorie_target: int
    bmi: float
    protein_g: int
    fat_g: int
    carbs_g: int
    # Daily reference amounts for the extra nutrients (see services/nutrients.py).
    nutrient_targets: dict[str, int] | None = None
