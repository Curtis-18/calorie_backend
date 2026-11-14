from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class NutrientsIn(BaseModel):
    """Extra nutrients for the portion eaten (not per 100 g). Leave a field
    out when the amount is unknown; never send 0 for "don't know"."""

    fiber_g: float | None = Field(None, ge=0, le=1000)
    sugar_g: float | None = Field(None, ge=0, le=5000)
    sodium_mg: float | None = Field(None, ge=0, le=200000)
    iron_mg: float | None = Field(None, ge=0, le=5000)
    calcium_mg: float | None = Field(None, ge=0, le=200000)

    def known(self) -> dict[str, float]:
        return {k: v for k, v in self.model_dump().items() if v is not None}


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
    nutrients: NutrientsIn | None = None  # None = unknown (e.g. a manual entry)


class FoodLogUpdate(BaseModel):
    """Corrections to a saved entry. Any subset; omitted fields are left
    alone. The id, source, date and time of the entry never change."""

    name: str | None = Field(None, min_length=1, max_length=200)
    calories: int | None = Field(None, ge=0)
    protein_g: float | None = Field(None, ge=0)
    carbs_g: float | None = Field(None, ge=0)
    fat_g: float | None = Field(None, ge=0)
    meal_type: Literal["breakfast", "lunch", "dinner", "snack"] | None = None
    # Unlike the fields above, sending null here clears the stored nutrients
    # (the food was swapped for one with no data). Leave it out to keep them.
    nutrients: NutrientsIn | None = None


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
    # Known extra nutrients for this entry, or None when there is no data.
    nutrients: dict[str, float] | None = None
