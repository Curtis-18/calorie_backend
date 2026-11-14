from datetime import date, datetime, timezone
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

# Upper bounds so one request can't store absurd or non-finite numbers:
# Infinity passed `ge=0`, was saved, and then every read of that day failed
# because it can't be written as JSON. Far above any real entry.
MAX_CALORIES = 100_000
MAX_MACRO_G = 20_000
MAX_NAME = 500


class NutrientsIn(BaseModel):
    """Extra nutrients for the portion eaten (not per 100 g). Leave a field
    out when the amount is unknown; never send 0 for "don't know"."""

    fiber_g: float | None = Field(None, ge=0, le=1000, allow_inf_nan=False)
    sugar_g: float | None = Field(None, ge=0, le=5000, allow_inf_nan=False)
    sodium_mg: float | None = Field(None, ge=0, le=200000, allow_inf_nan=False)
    iron_mg: float | None = Field(None, ge=0, le=5000, allow_inf_nan=False)
    calcium_mg: float | None = Field(None, ge=0, le=200000, allow_inf_nan=False)

    def known(self) -> dict[str, float]:
        return {k: v for k, v in self.model_dump().items() if v is not None}


class FoodLogIn(BaseModel):
    id: str = Field(min_length=1, max_length=300)
    name: str = Field(min_length=1, max_length=MAX_NAME)
    # ge, not gt: water, black coffee, tea and diet drinks are 0 kcal and
    # must be loggable.
    calories: int = Field(ge=0, le=MAX_CALORIES)
    protein_g: float = Field(ge=0, le=MAX_MACRO_G, default=0, allow_inf_nan=False)
    carbs_g: float = Field(ge=0, le=MAX_MACRO_G, default=0, allow_inf_nan=False)
    fat_g: float = Field(ge=0, le=MAX_MACRO_G, default=0, allow_inf_nan=False)
    meal_type: Literal["breakfast", "lunch", "dinner", "snack"]
    source: Literal["manual", "photo"]
    timestamp: datetime
    log_date: date  # the device-local "today" this entry belongs to
    nutrients: NutrientsIn | None = None  # None = unknown (e.g. a manual entry)

    @field_validator("timestamp")
    @classmethod
    def _naive_timestamp(cls, v: datetime) -> datetime:
        # The column is TIMESTAMP WITHOUT TIME ZONE and asyncpg refuses an
        # aware value, so a client sending "...Z" got a 500. The app sends
        # local time with no offset; anything with one is stored as UTC.
        return v.astimezone(timezone.utc).replace(tzinfo=None) if v.tzinfo else v


class FoodLogUpdate(BaseModel):
    """Corrections to a saved entry. Any subset; omitted fields are left
    alone. The id, source, date and time of the entry never change."""

    name: str | None = Field(None, min_length=1, max_length=MAX_NAME)
    calories: int | None = Field(None, ge=0, le=MAX_CALORIES)
    protein_g: float | None = Field(None, ge=0, le=MAX_MACRO_G, allow_inf_nan=False)
    carbs_g: float | None = Field(None, ge=0, le=MAX_MACRO_G, allow_inf_nan=False)
    fat_g: float | None = Field(None, ge=0, le=MAX_MACRO_G, allow_inf_nan=False)
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
