from datetime import date as date_type

from pydantic import BaseModel, Field

from app.services.weight_service import MAX_WEIGHT_KG, MIN_WEIGHT_KG


class WeightIn(BaseModel):
    weight_kg: float = Field(ge=MIN_WEIGHT_KG, le=MAX_WEIGHT_KG)
    # The device-local day of the weigh-in; defaults to today.
    date: date_type | None = None


class WeightPoint(BaseModel):
    date: date_type
    weight_kg: float
    trend_kg: float


class WeightSummary(BaseModel):
    start_kg: float
    start_date: date_type
    current_kg: float
    current_date: date_type
    trend_kg: float
    change_kg: float
    raw_change_kg: float
    lowest_kg: float
    highest_kg: float
    count: int
    days_since_last: int


class WeightHistoryOut(BaseModel):
    entries: list[WeightPoint]
    summary: WeightSummary | None


class WeightSavedOut(BaseModel):
    history: WeightHistoryOut
    targets_updated: bool
    notice: str | None = None
