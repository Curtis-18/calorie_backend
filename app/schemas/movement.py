import uuid
from datetime import date as date_type, datetime

from pydantic import BaseModel, Field, field_validator

from app.services import movement


class SetIn(BaseModel):
    """One set of a rep move in a guided session (NEXT_STEPS 9b)."""

    move: str = Field(..., max_length=40)
    reps: int = Field(..., ge=1, le=500, strict=True)


class MovementIn(BaseModel):
    id: uuid.UUID = Field(..., description="Chosen by the app so a retry cannot log twice")
    # A guided routine (its slice and effort come from the library), or a kind
    # of activity from the short list for logging by hand.
    routine_id: str | None = Field(default=None, max_length=40)
    activity: str | None = Field(default=None, max_length=40)
    minutes: int = Field(..., ge=1, le=600)
    intensity: str | None = None
    # The person's own day (device-local); the server's UTC date when absent.
    date: date_type | None = None
    # Guided sessions only: how many reps of each move were done, for "Last
    # time" next time. Optional; older apps don't send it.
    sets: list[SetIn] | None = Field(default=None, max_length=100)

    @field_validator("intensity")
    @classmethod
    def _known_intensity(cls, v: str | None) -> str | None:
        if v is not None and v not in movement.INTENSITIES:
            raise ValueError("Pick easy, moderate or hard.")
        return v


class MovementOut(BaseModel):
    id: uuid.UUID
    date: date_type
    activity: str
    label: str
    slice: str
    minutes: int
    intensity: str
    routine_id: str | None = None
    source: str
    est_kcal: int | None = None
    created_at: datetime | None = None


class SliceTotal(BaseModel):
    minutes: int
    sessions: int


class WeekOut(BaseModel):
    week_start: date_type
    minutes: int
    sessions: int
    active_days: int
    moved_days: list[bool]
    today_index: int
    by_slice: dict[str, SliceTotal]
    strength_days: int
    today_minutes: int
    today_sessions: int
    goal_minutes: int
    strength_days_goal: int
    week_moved: bool
    streak: int
    # The opt-in share of today's rough estimates added to the day's plan (0 = off).
    eat_back_percent: int = 0
    eat_back_kcal: int = 0
