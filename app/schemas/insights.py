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
    # This week's logged movement (Workouts tab), for one quiet line on Insights.
    # 0 when there is none, the backend is older or it could not be read.
    movement_minutes: int = 0
    movement_days: int = 0