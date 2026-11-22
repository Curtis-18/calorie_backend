"""Movement: what counts, the weekly maths and a rough energy estimate
(roadmap R9). Pure functions, so every rule is easy to read and test.

Rules (R2.3): movement is never a punishment or a payment for food. The energy
estimate is shown only to the person, labelled an estimate, and is NOT added to
the day's calorie target (the targets already include an activity level, so
adding it again would count it twice).
"""

from __future__ import annotations

from datetime import date, timedelta

from app.i18n import t
from app.services import workouts

SLICES = workouts.SLICES
INTENSITIES = ("easy", "moderate", "hard")
LEVEL_INTENSITY = {"easy": "easy", "steady": "moderate", "strong": "hard"}

# activity key: (label, slice, MET at easy / moderate / hard, offered to log by hand)
# MET values are deliberately on the cautious side of the Compendium of Physical
# Activities (which itself is partly estimated), and only the part above rest is
# counted (see estimate_kcal).
ACTIVITIES: dict[str, tuple[str, str, tuple[float, float, float], bool]] = {
    "walk": ("Walk", "cardio", (2.8, 3.5, 4.3), True),
    "run": ("Run", "cardio", (6.0, 8.3, 10.0), True),
    "cycle": ("Cycle", "cardio", (4.0, 6.8, 8.5), True),
    "swim": ("Swim", "cardio", (4.5, 6.0, 8.0), True),
    "gym": ("Gym or weights", "strength", (3.0, 3.5, 6.0), True),
    "home_strength": ("Strength at home", "strength", (3.0, 3.8, 5.0), True),
    "yoga": ("Yoga or stretching", "mobility", (2.0, 2.5, 3.3), True),
    "dance": ("Dance", "fun", (3.5, 4.5, 6.0), True),
    "sport": ("Sport or play", "fun", (4.0, 6.0, 8.0), True),
    "session_strength": ("Strength session", "strength", (3.0, 3.8, 5.0), False),
    "session_cardio": ("Cardio session", "cardio", (3.5, 5.0, 6.5), False),
    "session_mobility": ("Mobility session", "mobility", (2.0, 2.3, 2.8), False),
    "session_fun": ("Dance and play session", "fun", (3.5, 4.5, 6.0), False),
}

# The weekly guide. WHO (2020, adults): 150 to 300 minutes of moderate activity
# a week and muscle strengthening on 2 or more days. A "moved week" asks for
# about half of the low end, or three separate active days, so a busy or tired
# week can still count.
WEEK_GUIDE_MINUTES = 150
STRENGTH_DAYS_GUIDE = 2
GENTLE_WEEK_MINUTES = 75
GENTLE_WEEK_DAYS = 3
# A missed week is forgiven (keeps the run, adds nothing) at most once in any five.
FORGIVE_EVERY = 5
MAX_WEEKS_BACK = 52


def manual_choices() -> list[str]:
    return [k for k, v in ACTIVITIES.items() if v[3]]


def slice_for(activity: str) -> str | None:
    found = ACTIVITIES.get(activity)
    return found[1] if found else None


def label_for(activity: str, lang: str = "en") -> str:
    found = ACTIVITIES.get(activity)
    return t(lang, found[0]) if found else activity


def session_activity(routine: workouts.Routine) -> str:
    return f"session_{workouts.slice_of(routine)}"


def session_intensity(routine: workouts.Routine) -> str:
    return LEVEL_INTENSITY[routine.level]


def estimate_kcal(activity: str, intensity: str, minutes: int, weight_kg: float | None) -> int | None:
    """A rough figure for the part above resting: (MET - 1) x kg x hours, to the
    nearest 10. None when the weight or the activity is not known."""
    found = ACTIVITIES.get(activity)
    if found is None or intensity not in INTENSITIES or not weight_kg or weight_kg <= 0 or minutes <= 0:
        return None
    met = found[2][INTENSITIES.index(intensity)]
    kcal = (met - 1.0) * float(weight_kg) * (minutes / 60.0)
    return max(0, int(round(kcal / 10.0)) * 10)


# ---- the week -------------------------------------------------------------------------------------

def week_start(day: date) -> date:
    """The Monday of the week [day] is in."""
    return day - timedelta(days=day.weekday())


def is_moved_week(minutes: int, active_days: int) -> bool:
    return minutes >= GENTLE_WEEK_MINUTES or active_days >= GENTLE_WEEK_DAYS


def summarise_week(rows: list[tuple[date, str, int]], today: date) -> dict:
    """[rows] are (day, slice, minutes). Only the week [today] is in is counted."""
    start = week_start(today)
    days = [start + timedelta(days=i) for i in range(7)]
    this_week = [(d, s, m) for d, s, m in rows if start <= d <= days[-1] and s in SLICES]
    by_slice = {s: {"minutes": 0, "sessions": 0} for s in SLICES}
    for _, s, m in this_week:
        by_slice[s]["minutes"] += m
        by_slice[s]["sessions"] += 1
    moved_dates = {d for d, _, _ in this_week}
    strength_dates = {d for d, s, _ in this_week if s == "strength"}
    minutes = sum(m for _, _, m in this_week)
    return {
        "week_start": start,
        "minutes": minutes,
        "sessions": len(this_week),
        "active_days": len(moved_dates),
        "moved_days": [d in moved_dates for d in days],
        "today_index": (today - start).days,
        "by_slice": by_slice,
        "strength_days": len(strength_dates),
        "today_minutes": sum(m for d, _, m in this_week if d == today),
        "today_sessions": sum(1 for d, _, _ in this_week if d == today),
        "goal_minutes": WEEK_GUIDE_MINUTES,
        "strength_days_goal": STRENGTH_DAYS_GUIDE,
        "week_moved": is_moved_week(minutes, len(moved_dates)),
    }


def moved_weeks(rows: list[tuple[date, str, int]], today: date) -> int:
    """How many weeks in a row were "moved weeks", counting back from now.

    The week in progress is never a break: if it already counts it is the first
    link, and if not the count starts from last week. One missed week is
    forgiven (it keeps the run but adds nothing) at most once in any five weeks.
    Rest days inside a week never matter."""
    per_week: dict[date, tuple[int, set[date]]] = {}
    for d, s, m in rows:
        if s not in SLICES:
            continue
        w = week_start(d)
        minutes, days = per_week.get(w, (0, set()))
        days.add(d)
        per_week[w] = (minutes + m, days)

    current = week_start(today)

    def moved(i: int) -> bool:
        minutes, days = per_week.get(current - timedelta(weeks=i), (0, set()))
        return is_moved_week(minutes, len(days))

    i = 0 if moved(0) else 1
    streak = 0
    since_forgiven = FORGIVE_EVERY  # a forgiveness is available at the start
    while i <= MAX_WEEKS_BACK:
        if moved(i):
            streak += 1
            since_forgiven += 1
        elif since_forgiven >= FORGIVE_EVERY - 1 and streak > 0 and i + 1 <= MAX_WEEKS_BACK and moved(i + 1):
            since_forgiven = 0  # forgiven: keeps the run, adds nothing
        else:
            break
        i += 1
    return streak
