"""Weekly calorie budget: a flexible daily allowance, and a gentle nudge.

A person who eats more at the weekend isn't failing; they are spending a
weekly budget differently. This turns the fixed daily target into an
*allowance* that eases a little after a bigger day and gives a little back
after a lighter one, always inside firm limits (handover: PRODUCT ROADMAP
P2.1 / P2.2, rules R2.2 and R2.4):

- no day's allowance ever goes below the calorie floor (1200 women, 1500 men)
  or more than 15% below the daily target;
- no day goes more than 15% above the target;
- a day with nothing logged is *unknown*: it neither banks nor owes anything;
- eating below the floor earns nothing back (it is counted as the floor);
- the bank is capped at one day's target, so a few light days can't be
  "spent" in one go.

Everything here is a pure function of the logs and the target, so there is
nothing to store or back-fill and a rule change re-scores history. All the
numbers are in one block of constants so they can be tuned after the client
has seen them. Past days' targets are not stored (the target follows the
latest weight), so the current target is used for the whole week.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

DAYS = 7
MAX_TRIM = 0.15       # an allowance never goes more than this far below the target
MAX_BONUS = 0.15      # ... or above it
BANK_CAP_DAYS = 1.0   # leftover that can be carried, in days of target
# A nudge appears only when today is over by more than this (kcal, or a share
# of the allowance, whichever is larger).
NUDGE_MIN_OVER_KCAL = 150
NUDGE_MIN_OVER_SHARE = 0.08
# Weekday weights ("weekend flex") must stay inside these.
WEIGHT_MIN = 1 - MAX_TRIM
WEIGHT_MAX = 1 + MAX_BONUS

DayState = Literal["past_logged", "past_unlogged", "today", "future"]


@dataclass(frozen=True)
class DayBudget:
    day: date
    base: int            # the plan for the day (target x weight)
    eaten: int | None    # None = nothing logged
    state: DayState
    allowance: int       # what to aim for; for past days, what it was worth


@dataclass(frozen=True)
class WeekBudget:
    week_start: date
    days: list[DayBudget]
    today: DayBudget
    bank: int            # kcal carried into today (+ leftover, - extra)


def week_start_of(day: date, start_day: int = 0) -> date:
    """The first day of the week containing [day]; [start_day] is 0 = Monday."""
    return day - timedelta(days=(day.weekday() - start_day) % 7)


def valid_weights(weights: list[float] | None, target: int, floor: int) -> bool:
    """Whether per-weekday weights are acceptable: seven of them, adding up to
    seven, each within the limits and never putting a day under the floor."""
    if weights is None:
        return True
    if len(weights) != DAYS or any(not isinstance(w, (int, float)) for w in weights):
        return False
    if abs(sum(weights) - DAYS) > 0.01:
        return False
    return all(max(WEIGHT_MIN, floor / target) - 1e-9 <= w <= WEIGHT_MAX + 1e-9 for w in weights)


def _bounds(target: int, floor: int) -> tuple[float, float]:
    return max(floor, target * (1 - MAX_TRIM)), target * (1 + MAX_BONUS)


def compute_week_budget(
    *,
    today: date,
    target: int,
    floor: int,
    eaten_by_date: dict[date, int],
    start_day: int = 0,
    weights: list[float] | None = None,
) -> WeekBudget:
    """The week around [today]. [eaten_by_date] holds calories for days that
    have at least one entry (a day missing from it is unknown)."""
    if weights is None or not valid_weights(weights, target, floor):
        weights = [1.0] * DAYS
    start = week_start_of(today, start_day)
    index_today = (today - start).days
    low, high = _bounds(target, floor)

    def base_for(i: int) -> int:
        # Weights are listed from the first day of the week.
        return round(target * weights[i])

    carry = 0.0
    for i in range(index_today):
        eaten = eaten_by_date.get(start + timedelta(days=i))
        if eaten is None:
            continue
        # Under the floor counts as the floor: not eating earns nothing.
        carry += base_for(i) - max(eaten, floor)
    carry = min(carry, target * BANK_CAP_DAYS)

    days_left = DAYS - index_today  # today included
    adjustment = carry / days_left

    days: list[DayBudget] = []
    for i in range(DAYS):
        day = start + timedelta(days=i)
        base = base_for(i)
        eaten = eaten_by_date.get(day)
        if i < index_today:
            state: DayState = "past_logged" if eaten is not None else "past_unlogged"
            allowance = base
        elif i == index_today:
            state = "today"
            allowance = round(min(max(base + adjustment, low), high))
        else:
            state = "future"
            allowance = base
        days.append(DayBudget(day=day, base=base, eaten=eaten, state=state, allowance=allowance))
    return WeekBudget(week_start=start, days=days, today=days[index_today], bank=round(carry))


@dataclass(frozen=True)
class Nudge:
    kind: Literal["spread", "too_big"]
    over_by: int
    days: int
    per_day: int | None
    message: str


def compute_nudge(
    *,
    shown_allowance: int,
    eaten_today: int,
    days_left_after_today: int,
    target: int,
    floor: int,
    goal: str,
) -> Nudge | None:
    """A kind, optional suggestion after a bigger day, or None.

    No nudge for a gain goal (more food is not the problem), on the last day
    of the week (nothing left to spread over), or for a small overage. The
    suggested trim per day must fit inside the same limits as the allowance;
    if it can't, the message says a normal day is fine and offers nothing.
    """
    if goal == "gain" or days_left_after_today < 1:
        return None
    over = eaten_today - shown_allowance
    if over <= max(NUDGE_MIN_OVER_KCAL, NUDGE_MIN_OVER_SHARE * shown_allowance):
        return None

    max_trim_per_day = max(0.0, min(target * MAX_TRIM, target - floor))
    per_day = _round_up(over / days_left_after_today, 10)
    if per_day > max_trim_per_day or max_trim_per_day < 10:
        return Nudge(
            kind="too_big",
            over_by=round(over),
            days=days_left_after_today,
            per_day=None,
            message="Today was a bigger one, and that's fine. A normal day tomorrow is all you need.",
        )
    return Nudge(
        kind="spread",
        over_by=round(over),
        days=days_left_after_today,
        per_day=per_day,
        message=(
            f"You're about {_round_to(over, 10)} over today. "
            f"Want to ease about {per_day} a day over the next {days_left_after_today} "
            f"day{'s' if days_left_after_today != 1 else ''}?"
        ),
    )


def _round_up(value: float, step: int) -> int:
    return int(-(-value // step) * step)


def _round_to(value: float, step: int) -> int:
    return int(round(value / step) * step)
