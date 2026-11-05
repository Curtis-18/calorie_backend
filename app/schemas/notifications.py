from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class PrefsOut(BaseModel):
    friend_snaps: bool
    reactions: bool
    streak_reminders: bool
    milestones: bool
    meal_nudge_hour: int | None
    quiet_start: int
    quiet_end: int
    utc_offset_minutes: int
    paused_until: datetime | None
    daily_cap: int


class PrefsIn(BaseModel):
    """Any subset. Omitted fields are left alone."""

    friend_snaps: bool | None = None
    reactions: bool | None = None
    streak_reminders: bool | None = None
    milestones: bool | None = None
    # Local hour for the optional meal reminder; -1 turns it off.
    meal_nudge_hour: int | None = Field(None, ge=-1, le=23)
    quiet_start: int | None = Field(None, ge=0, le=23)
    quiet_end: int | None = Field(None, ge=0, le=23)
    utc_offset_minutes: int | None = Field(None, ge=-840, le=840)
    # Pause everything for this many days; 0 resumes now.
    pause_days: int | None = Field(None, ge=0, le=14)


class DeviceIn(BaseModel):
    token: str = Field(..., min_length=16, max_length=4096)
    platform: Literal["ios", "android"]
    utc_offset_minutes: int | None = Field(None, ge=-840, le=840)
