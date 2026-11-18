"""Habit patterns and a weekly summary, computed from the food log.

The numbers and the sentences are produced here, by code. Nothing is asked of
a language model, so nothing can be invented: every claim is one the data
passed a threshold for (handover: PRODUCT ROADMAP P2.3). A pattern is only
reported with enough logged days on each side of the comparison, and at most
two are shown a week, strongest first.

Two data-quality rules:
- `food_logs.timestamp` is when an entry was *saved*, not eaten. Time-of-day
  statements use only entries saved on the day they belong to (live logging),
  and the wording says "when you log".
- A day with nothing logged is unknown, never "ate nothing".

Wording rules (R2.3, R2.4): neutral, positive tips only, never a "lowest day"
or a suggestion to eat less, never exercise as a fix.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from statistics import mean

WINDOW_DAYS = 28
MIN_DAYS_FOR_PATTERNS = 14
LATE_HOUR = 20                 # 8 PM
LOW_LUNCH_PROTEIN_G = 25
MIN_DAYS_EACH_SIDE = 4
MIN_LATE_SHARE_GAP = 0.10      # percentage points, as a fraction
MIN_WEEKEND_GAP = 0.10
MIN_WEEKEND_DAYS = 3
MIN_WEEKDAY_DAYS = 6
MIN_LATE_DAYS = 10
HIGH_LATE_SHARE = 0.35
PROTEIN_GOAL_SHARE = 0.9       # a day "hits" protein at 90% of the target
MAX_PATTERNS = 2


@dataclass(frozen=True)
class Entry:
    log_date: date
    timestamp: datetime
    meal_type: str
    calories: int
    protein_g: float


@dataclass(frozen=True)
class DayFeatures:
    day: date
    calories: int
    protein_g: float
    lunch_protein_g: float | None   # None = no lunch logged
    late_share: float | None        # None = no live entries to judge by


@dataclass(frozen=True)
class Pattern:
    id: str
    text: str
    tip: str
    strength: float


def day_features(entries: list[Entry]) -> list[DayFeatures]:
    by_day: dict[date, list[Entry]] = {}
    for e in entries:
        by_day.setdefault(e.log_date, []).append(e)
    out = []
    for day, items in sorted(by_day.items()):
        calories = sum(e.calories for e in items)
        if calories <= 0:
            continue  # nothing real was logged
        lunch = [e for e in items if e.meal_type == "lunch"]
        live = [e for e in items if e.timestamp.date() == e.log_date]
        live_total = sum(e.calories for e in live)
        late = sum(e.calories for e in live if e.timestamp.hour >= LATE_HOUR)
        out.append(
            DayFeatures(
                day=day,
                calories=calories,
                protein_g=sum(e.protein_g for e in items),
                lunch_protein_g=sum(e.protein_g for e in lunch) if lunch else None,
                late_share=(late / live_total) if live_total > 0 else None,
            )
        )
    return out


def _pct(x: float) -> int:
    return round(x * 100)


def find_patterns(days: list[DayFeatures]) -> list[Pattern]:
    if len(days) < MIN_DAYS_FOR_PATTERNS:
        return []
    found: list[Pattern] = []

    # 1. Evenings after a light-protein lunch.
    rated = [d for d in days if d.lunch_protein_g is not None and d.late_share is not None]
    low = [d.late_share for d in rated if d.lunch_protein_g < LOW_LUNCH_PROTEIN_G]
    high = [d.late_share for d in rated if d.lunch_protein_g >= LOW_LUNCH_PROTEIN_G]
    if len(low) >= MIN_DAYS_EACH_SIDE and len(high) >= MIN_DAYS_EACH_SIDE:
        gap = mean(low) - mean(high)
        if gap >= MIN_LATE_SHARE_GAP:
            found.append(Pattern(
                id="lunch_protein_evening",
                text=(
                    f"On days you log under {LOW_LUNCH_PROTEIN_G} g of protein at lunch, about {_pct(mean(low))}% "
                    f"of your calories are logged after 8 PM, compared with {_pct(mean(high))}% on other days."
                ),
                tip="A protein-rich lunch (eggs, yogurt, beans, chicken) might help evenings feel steadier. Worth trying for a week.",
                strength=gap,
            ))

    # 2. Weekends running higher than weekdays.
    weekday = [d.calories for d in days if d.day.weekday() < 5]
    weekend = [d.calories for d in days if d.day.weekday() >= 5]
    if len(weekday) >= MIN_WEEKDAY_DAYS and len(weekend) >= MIN_WEEKEND_DAYS:
        ratio = mean(weekend) / mean(weekday)
        if ratio - 1 >= MIN_WEEKEND_GAP:
            found.append(Pattern(
                id="weekend_higher",
                text=f"Your weekends tend to be about {_pct(ratio - 1)}% higher than your weekdays.",
                tip="That's very normal. Weekend flex in Settings plans for it, so the week still balances.",
                strength=ratio - 1,
            ))

    # 3. A big share of the day logged late.
    shares = [d.late_share for d in days if d.late_share is not None]
    if len(shares) >= MIN_LATE_DAYS and mean(shares) >= HIGH_LATE_SHARE:
        found.append(Pattern(
            id="late_share",
            text=f"About {_pct(mean(shares))}% of the calories you log come after 8 PM.",
            tip="If you'd like to even things out, a planned afternoon snack with some protein can help.",
            strength=mean(shares) - HIGH_LATE_SHARE + 0.05,
        ))

    found.sort(key=lambda p: p.strength, reverse=True)
    return found[:MAX_PATTERNS]


def weekly_summary(days: list[DayFeatures], today: date, protein_target: int | None) -> dict:
    start = today - timedelta(days=6)
    week = [d for d in days if start <= d.day <= today]
    protein_days = None
    if protein_target:
        protein_days = sum(1 for d in week if d.protein_g >= protein_target * PROTEIN_GOAL_SHARE)
    return {"days_logged": len(week), "protein_goal_days": protein_days}


def summary_message(days_logged: int) -> str:
    if days_logged == 0:
        return "A fresh week. Log anything today and your week starts to fill in."
    if days_logged >= 6:
        return f"You logged {days_logged} of the last 7 days. That consistency is what makes the difference."
    return f"You logged {days_logged} of the last 7 days. Every day you log makes your insights sharper."


def build_report(entries: list[Entry], today: date, protein_target: int | None) -> dict:
    days = day_features(entries)
    summary = weekly_summary(days, today, protein_target)
    enough = len(days) >= MIN_DAYS_FOR_PATTERNS
    patterns = find_patterns(days)
    return {
        **summary,
        "protein_target": protein_target,
        "message": summary_message(summary["days_logged"]),
        "logged_days_recently": len(days),
        "enough_data": enough,
        "days_needed": max(0, MIN_DAYS_FOR_PATTERNS - len(days)),
        "patterns": [{"id": p.id, "text": p.text, "tip": p.tip} for p in patterns],
    }
