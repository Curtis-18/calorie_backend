from typing import Literal
from pydantic import BaseModel, Field
from datetime import date


class OnboardingIn(BaseModel):
    date_of_birth: date
    sex: Literal["male", "female"]
    height_feet: int = Field(ge=3, le=8)
    height_inches: float = Field(ge=0, lt=12, default=0)
    weight_value: float = Field(gt=0)
    weight_unit: Literal["kg", "lb"]
    activity_level: Literal["sedentary", "light", "moderate", "active", "very_active"]
    goal: Literal["lose", "maintain", "gain"]


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