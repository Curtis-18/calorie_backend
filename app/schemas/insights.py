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