"""Gamification: streaks, freezes, XP, levels and achievements.

Everything here is *derived* from a user's food logs and targets on every
request, never stored. That keeps it identical on every device, impossible to
double-count with retries or double taps, and needs no migration. Changing a
rule below re-scores history consistently.

Design rule: reward consistency and balance, never eating less. A "perfect
day" is landing *within* a band around the target, and no XP is ever given
for a low total.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

MEAL_TYPES = frozenset({"breakfast", "lunch", "dinner", "snack"})

# XP rules (per day). Caps stop a burst of tiny logs from farming XP.
XP_PER_ENTRY = 10
MAX_SCORED_ENTRIES_PER_DAY = 6
XP_PER_PHOTO = 5
MAX_SCORED_PHOTOS_PER_DAY = 3
XP_FULL_HOUSE = 20  # breakfast, lunch, dinner and a snack in one day
XP_PROTEIN_GOAL = 20
XP_PERFECT_DAY = 30
XP_STREAK_PER_DAY = 2  # x current streak length...
MAX_STREAK_BONUS = 30  # ...capped

# A perfect day lands within this band of the calorie target.
PERFECT_LOW = 0.9
PERFECT_HIGH = 1.1

# One freeze is earned every FREEZE_EVERY streak days, holding at most
# MAX_FREEZES. A missed day spends one automatically instead of resetting.
FREEZE_EVERY = 7
MAX_FREEZES = 2

EARLY_BIRD_HOUR = 9

# Flame tiers by current streak length (minimum days).
TIERS = [(30, "inferno"), (14, "blaze"), (7, "flame"), (3, "ember"), (0, "spark")]


def tier_for(streak: int) -> str:
    return next(name for minimum, name in TIERS if streak >= minimum)


def xp_for_level(level: int) -> int:
    """Total XP needed to reach [level]: 0, 100, 300, 600, 1000, ..."""
    return 50 * level * (level - 1)


def level_for(xp: int) -> int:
    level = 1
    while xp_for_level(level + 1) <= xp:
        level += 1
    return level


@dataclass
class LogRow:
    log_date: date
    meal_type: str
    source: str
    calories: int
    protein_g: float
    timestamp: datetime | None = None


@dataclass
class DayStats:
    entries: int = 0
    photos: int = 0
    calories: int = 0
    protein_g: float = 0.0
    meal_types: set[str] = field(default_factory=set)
    early_breakfast: bool = False


@dataclass(frozen=True)
class Achievement:
    id: str
    title: str
    description: str
    goal: int = 1


ACHIEVEMENTS = [
    Achievement("first_bite", "First Bite", "Log your first meal."),
    Achievement("snapshot", "Snapshot", "Log a meal by scanning a photo."),
    Achievement("early_bird", "Early Bird", f"Log breakfast before {EARLY_BIRD_HOUR} am."),
    Achievement("full_house", "Full House", "Log breakfast, lunch, dinner and a snack in one day."),
    Achievement("bullseye", "Bullseye", "Land within 10% of your calorie target."),
    Achievement("protein_pro", "Protein Pro", "Hit your protein target 5 days in a row.", goal=5),
    Achievement("on_fire", "On Fire", "Keep a 7-day streak.", goal=7),
    Achievement("inferno", "Inferno", "Keep a 30-day streak.", goal=30),
    Achievement("centurion", "Centurion", "Log 100 meals.", goal=100),
]


def group_by_day(rows: list[LogRow]) -> dict[date, DayStats]:
    days: dict[date, DayStats] = {}
    for row in rows:
        d = days.setdefault(row.log_date, DayStats())
        d.entries += 1
        d.calories += row.calories
        d.protein_g += row.protein_g or 0
        if row.source == "photo":
            d.photos += 1
        if row.meal_type in MEAL_TYPES:
            d.meal_types.add(row.meal_type)
        if (
            row.meal_type == "breakfast"
            and row.timestamp is not None
            and row.timestamp.hour < EARLY_BIRD_HOUR
        ):
            d.early_breakfast = True
    return days


def is_perfect(stats: DayStats, calorie_target: int | None) -> bool:
    if not calorie_target or stats.entries == 0:
        return False
    return PERFECT_LOW * calorie_target <= stats.calories <= PERFECT_HIGH * calorie_target


def hit_protein(stats: DayStats, protein_target: int | None) -> bool:
    return bool(protein_target) and stats.entries > 0 and stats.protein_g >= protein_target


def day_xp(stats: DayStats, streak: int, calorie_target: int | None, protein_target: int | None) -> int:
    xp = XP_PER_ENTRY * min(stats.entries, MAX_SCORED_ENTRIES_PER_DAY)
    xp += XP_PER_PHOTO * min(stats.photos, MAX_SCORED_PHOTOS_PER_DAY)
    if stats.meal_types >= MEAL_TYPES:
        xp += XP_FULL_HOUSE
    if hit_protein(stats, protein_target):
        xp += XP_PROTEIN_GOAL
    if is_perfect(stats, calorie_target):
        xp += XP_PERFECT_DAY
    xp += min(XP_STREAK_PER_DAY * streak, MAX_STREAK_BONUS)
    return xp


def compute_progress(
    rows: list[LogRow],
    today: date,
    calorie_target: int | None,
    protein_target: int | None,
) -> dict:
    """Score a user's whole history up to and including [today].

    Logs dated after [today] (another device a timezone ahead) are ignored.
    """
    days = group_by_day([r for r in rows if r.log_date <= today])

    streak = best_streak = freezes = 0
    xp = total_meals = protein_run = best_protein_run = 0
    frozen_days: list[date] = []
    unlocked: dict[str, date] = {}

    def unlock(achievement_id: str, on: date) -> None:
        unlocked.setdefault(achievement_id, on)

    if days:
        day = min(days)
        while day <= today:
            stats = days.get(day)
            if stats:
                streak += 1
                best_streak = max(best_streak, streak)
                if streak % FREEZE_EVERY == 0:
                    freezes = min(freezes + 1, MAX_FREEZES)
                xp += day_xp(stats, streak, calorie_target, protein_target)
                total_meals += stats.entries

                if hit_protein(stats, protein_target):
                    protein_run += 1
                    best_protein_run = max(best_protein_run, protein_run)
                elif day != today:  # today can still get there
                    protein_run = 0

                unlock("first_bite", day)
                if stats.photos:
                    unlock("snapshot", day)
                if stats.early_breakfast:
                    unlock("early_bird", day)
                if stats.meal_types >= MEAL_TYPES:
                    unlock("full_house", day)
                if is_perfect(stats, calorie_target):
                    unlock("bullseye", day)
                if best_protein_run >= 5:
                    unlock("protein_pro", day)
                if best_streak >= 7:
                    unlock("on_fire", day)
                if best_streak >= 30:
                    unlock("inferno", day)
                if total_meals >= 100:
                    unlock("centurion", day)
            elif day != today:  # an unlogged today doesn't break anything yet
                protein_run = 0
                if streak > 0 and freezes > 0:
                    freezes -= 1
                    frozen_days.append(day)
                else:
                    streak = 0
            day += timedelta(days=1)

    today_stats = days.get(today, DayStats())
    level = level_for(xp)
    progress_values = {
        "first_bite": min(total_meals, 1),
        "snapshot": 1 if "snapshot" in unlocked else 0,
        "early_bird": 1 if "early_bird" in unlocked else 0,
        "full_house": 1 if "full_house" in unlocked else 0,
        "bullseye": 1 if "bullseye" in unlocked else 0,
        "protein_pro": best_protein_run,
        "on_fire": best_streak,
        "inferno": best_streak,
        "centurion": total_meals,
    }

    return {
        "date": today,
        "streak": {
            "current": streak,
            "best": best_streak,
            "tier": tier_for(streak),
            "freezes": freezes,
            "max_freezes": MAX_FREEZES,
            "logged_today": today_stats.entries > 0,
            "frozen_days": [d for d in frozen_days if (today - d).days < 30],
        },
        "level": {
            "level": level,
            "xp": xp,
            "level_xp": xp_for_level(level),
            "next_level_xp": xp_for_level(level + 1),
        },
        "today": {
            "xp": day_xp(today_stats, streak, calorie_target, protein_target) if today_stats.entries else 0,
            "perfect_day": is_perfect(today_stats, calorie_target),
            "calories": today_stats.calories,
            "target_low": round(PERFECT_LOW * calorie_target) if calorie_target else None,
            "target_high": round(PERFECT_HIGH * calorie_target) if calorie_target else None,
        },
        "achievements": [
            {
                "id": a.id,
                "title": a.title,
                "description": a.description,
                "unlocked": a.id in unlocked,
                "unlocked_on": unlocked.get(a.id),
                "progress": min(progress_values[a.id], a.goal),
                "goal": a.goal,
            }
            for a in ACHIEVEMENTS
        ],
    }
