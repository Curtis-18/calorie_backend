from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class FoodLogIn(BaseModel):
    id: str
    name: str
    # ge, not gt: water, black coffee, tea and diet drinks are 0 kcal and
    # must be loggable.
    calories: int = Field(ge=0)
    protein_g: float = Field(ge=0, default=0)
    carbs_g: float = Field(ge=0, default=0)
    fat_g: float = Field(ge=0, default=0)
    meal_type: Literal["breakfast", "lunch", "dinner", "snack"]
    source: Literal["manual", "photo"]
    timestamp: datetime
    log_date: date  # the device-local "today" this entry belongs to


class FoodLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    calories: int
    protein_g: float
    carbs_g: float
    fat_g: float
    meal_type: str
    source: str
    timestamp: datetime
    log_date: date