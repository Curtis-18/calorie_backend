from datetime import date

from pydantic import BaseModel


class StreakOut(BaseModel):
    current: int
    best: int
    tier: str  # spark | ember | flame | blaze | inferno
    freezes: int
    max_freezes: int
    logged_today: bool
    frozen_days: list[date]


class LevelOut(BaseModel):
    level: int
    xp: int
    level_xp: int  # total XP at the start of this level
    next_level_xp: int  # total XP needed for the next one


class TodayOut(BaseModel):
    xp: int
    perfect_day: bool
    calories: int
    target_low: int | None
    target_high: int | None


class AchievementOut(BaseModel):
    id: str
    title: str
    description: str
    unlocked: bool
    unlocked_on: date | None
    progress: int
    goal: int


class ProgressOut(BaseModel):
    date: date
    streak: StreakOut
    level: LevelOut
    today: TodayOut
    achievements: list[AchievementOut]
