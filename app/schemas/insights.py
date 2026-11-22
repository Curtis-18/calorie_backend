from datetime import date as date_type, datetime
from pydantic import BaseModel


class DayTrend(BaseModel):
    date: date_type
    calories: int
    protein_g: float
    carbs_g: float
    fat_g: float


class InsightsOut(BaseModel):
    narrative: str
    tips: list[str]
    weekly_trend: list[DayTrend]
    generated_at: datetime
    # Entries in the 7 days shown whose numbers are an estimate (a dish with no
    # database match). Lets the app say "some foods were estimated". 0 for an
    # older backend or when it could not be read.
    estimated_entries: int = 0