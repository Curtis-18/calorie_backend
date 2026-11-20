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
- Sugar and fibre come from the USDA match (`food_log_nutrients`). An entry
  with no data for one is *unknown*, never zero, and the sentences say "in the
  foods we could match". USDA's sugar is total sugar (fruit and milk included),
  so nothing here says "added sugar" or calls any food bad. A fibre day is only
  judged when the matched foods cover most of that day's calories.

Wording rules (R2.3, R2.4): neutral, positive tips only, never a "lowest day"
or a suggestion to eat less, never exercise as a fix.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from statistics import mean

from app.i18n import t

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
MIN_SUGAR_G_FOR_A_DAY = 10     # grams of known sugar needed before a day says anything about timing
MIN_SUGAR_GAP = 0.15           # share of sugar after 8 PM, low-protein-lunch days vs the rest
MIN_FIBRE_DAYS = 10            # days with enough matched food to judge fibre
FIBRE_COVERAGE = 0.6           # share of a day's calories that must have fibre data
FIBRE_LOW_SHARE_OF_TARGET = 0.8
FIBRE_LOW_DAYS_SHARE = 0.7
MAX_PATTERNS = 2


@dataclass(frozen=True)
class Entry:
    log_date: date
    timestamp: datetime
    meal_type: str
    calories: int
    protein_g: float
    sugar_g: float | None = None    # None = unknown for this entry
    fiber_g: float | None = None


@dataclass(frozen=True)
class DayFeatures:
    day: date
    calories: int
    protein_g: float
    lunch_protein_g: float | None   # None = no lunch logged
    late_share: float | None        # None = no live entries to judge by
    late_sugar_share: float | None = None  # None = too little known sugar to judge
    fiber_g: float | None = None    # None = matched foods cover too little of the day


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

        live_sugar = [e for e in live if e.sugar_g is not None]
        sugar_total = sum(e.sugar_g for e in live_sugar)
        late_sugar = sum(e.sugar_g for e in live_sugar if e.timestamp.hour >= LATE_HOUR)
        covered = sum(e.calories for e in items if e.fiber_g is not None)
        has_fibre = covered >= FIBRE_COVERAGE * calories
        out.append(
            DayFeatures(
                day=day,
                calories=calories,
                protein_g=sum(e.protein_g for e in items),
                lunch_protein_g=sum(e.protein_g for e in lunch) if lunch else None,
                late_share=(late / live_total) if live_total > 0 else None,
                late_sugar_share=(late_sugar / sugar_total) if sugar_total >= MIN_SUGAR_G_FOR_A_DAY else None,
                fiber_g=sum(e.fiber_g for e in items if e.fiber_g is not None) if has_fibre else None,
            )
        )
    return out


def _pct(x: float) -> int:
    return round(x * 100)


def find_patterns(days: list[DayFeatures], fiber_target: int | None = None, lang: str = "en") -> list[Pattern]:
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
                text=t(
                    lang,
                    "On days you log under {limit} g of protein at lunch, about {low}% of your calories are logged after 8 PM, compared with {high}% on other days.",
                    limit=LOW_LUNCH_PROTEIN_G, low=_pct(mean(low)), high=_pct(mean(high)),
                ),
                tip=t(lang, "A protein-rich lunch (eggs, yogurt, beans, chicken) might help evenings feel steadier. Worth trying for a week."),
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
                text=t(lang, "Your weekends tend to be about {pct}% higher than your weekdays.", pct=_pct(ratio - 1)),
                tip=t(lang, "That's very normal. Weekend flex in Settings plans for it, so the week still balances."),
                strength=ratio - 1,
            ))

    # 3. A big share of the day logged late.
    shares = [d.late_share for d in days if d.late_share is not None]
    if len(shares) >= MIN_LATE_DAYS and mean(shares) >= HIGH_LATE_SHARE:
        found.append(Pattern(
            id="late_share",
            text=t(lang, "About {pct}% of the calories you log come after 8 PM.", pct=_pct(mean(shares))),
            tip=t(lang, "If you'd like to even things out, a planned afternoon snack with some protein can help."),
            strength=mean(shares) - HIGH_LATE_SHARE + 0.05,
        ))

    # 4. Sugar after 8 PM on days with a light-protein lunch (the example in
    # the product notes). Only the foods with sugar data are counted.
    sugar_rated = [d for d in days if d.lunch_protein_g is not None and d.late_sugar_share is not None]
    s_low = [d.late_sugar_share for d in sugar_rated if d.lunch_protein_g < LOW_LUNCH_PROTEIN_G]
    s_high = [d.late_sugar_share for d in sugar_rated if d.lunch_protein_g >= LOW_LUNCH_PROTEIN_G]
    if len(s_low) >= MIN_DAYS_EACH_SIDE and len(s_high) >= MIN_DAYS_EACH_SIDE:
        gap = mean(s_low) - mean(s_high)
        if gap >= MIN_SUGAR_GAP:
            found.append(Pattern(
                id="lunch_protein_evening_sugar",
                text=t(
                    lang,
                    "On days you log under {limit} g of protein at lunch, about {low}% of the sugar in the foods we could match is logged after 8 PM, compared with {high}% on other days.",
                    limit=LOW_LUNCH_PROTEIN_G, low=_pct(mean(s_low)), high=_pct(mean(s_high)),
                ),
                tip=t(
                    lang,
                    "Some of that is natural sugar from fruit and milk, so it isn't about sweets. A protein-rich lunch might help evenings feel steadier. Worth trying for a week.",
                ),
                strength=gap,
            ))

    # 5. Fibre usually under the guide, judged only on days the matched foods
    # cover most of the calories.
    if fiber_target:
        judged = [d.fiber_g for d in days if d.fiber_g is not None]
        if len(judged) >= MIN_FIBRE_DAYS:
            low_days = sum(1 for f in judged if f < FIBRE_LOW_SHARE_OF_TARGET * fiber_target)
            share = low_days / len(judged)
            if share >= FIBRE_LOW_DAYS_SHARE:
                found.append(Pattern(
                    id="low_fibre",
                    text=t(
                        lang,
                        "On {low} of the {n} days we could check, the foods we matched came to under your fibre guide of about {target} g.",
                        low=low_days, n=len(judged), target=fiber_target,
                    ),
                    tip=t(lang, "Beans, lentils, oats, berries and whole grains are easy ways to add fibre, one swap at a time."),
                    strength=share - 0.5,
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


def summary_message(days_logged: int, lang: str = "en") -> str:
    if days_logged == 0:
        return t(lang, "A fresh week. Log anything today and your week starts to fill in.")
    if days_logged >= 6:
        return t(lang, "You logged {n} of the last 7 days. That consistency is what makes the difference.", n=days_logged)
    return t(lang, "You logged {n} of the last 7 days. Every day you log makes your insights sharper.", n=days_logged)


def build_report(
    entries: list[Entry], today: date, protein_target: int | None, fiber_target: int | None = None, lang: str = "en"
) -> dict:
    days = day_features(entries)
    summary = weekly_summary(days, today, protein_target)
    enough = len(days) >= MIN_DAYS_FOR_PATTERNS
    patterns = find_patterns(days, fiber_target, lang)
    return {
        **summary,
        "protein_target": protein_target,
        "message": summary_message(summary["days_logged"], lang),
        "logged_days_recently": len(days),
        "enough_data": enough,
        "days_needed": max(0, MIN_DAYS_FOR_PATTERNS - len(days)),
        "patterns": [{"id": p.id, "text": p.text, "tip": p.tip} for p in patterns],
    }
