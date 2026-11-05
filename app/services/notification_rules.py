"""When a notification may be sent, and what it says.

Pure functions, so the rules that keep notifications from being annoying are
easy to test. The principles, in order of importance:

1. Never more than DAILY_CAP a day, counted in the person's own day.
2. Never during quiet hours or while they have paused notifications.
3. Only for something real: a friend's snap or reaction, a streak about to
   break, a milestone. Never "we miss you".
4. Never about weight, calories or a missed meal, and never guilt. Copy is
   playful and short.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum

DAILY_CAP = 2


class Kind(str, Enum):
    FRIEND_SNAP = "friend_snap"
    REACTION = "reaction"
    STREAK_AT_RISK = "streak_at_risk"
    STREAK_FREEZE = "streak_freeze"
    MILESTONE = "milestone"
    MEAL_NUDGE = "meal_nudge"


# Which preference switch controls which kind.
_SWITCH = {
    Kind.FRIEND_SNAP: "friend_snaps",
    Kind.REACTION: "reactions",
    Kind.STREAK_AT_RISK: "streak_reminders",
    Kind.STREAK_FREEZE: "streak_reminders",
    Kind.MILESTONE: "milestones",
    Kind.MEAL_NUDGE: None,  # scheduled on the phone, by its own hour setting
}


@dataclass(frozen=True)
class Prefs:
    friend_snaps: bool = True
    reactions: bool = True
    streak_reminders: bool = True
    milestones: bool = True
    meal_nudge_hour: int | None = None
    quiet_start: int = 22
    quiet_end: int = 8
    utc_offset_minutes: int = 0
    paused_until: datetime | None = None


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str = ""


def local_time(now_utc: datetime, prefs: Prefs) -> datetime:
    return now_utc + timedelta(minutes=prefs.utc_offset_minutes)


def local_day_bounds_utc(now_utc: datetime, prefs: Prefs) -> tuple[datetime, datetime]:
    """The person's current local day as a [start, end) range in UTC."""
    local = local_time(now_utc, prefs)
    start_local = local.replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = start_local - timedelta(minutes=prefs.utc_offset_minutes)
    return start_utc, start_utc + timedelta(days=1)


def in_quiet_hours(hour: int, start: int, end: int) -> bool:
    """[start, end) on a 24 hour clock, wrapping past midnight (22 to 8)."""
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def decide(kind: Kind, prefs: Prefs, now_utc: datetime, sent_today: int, *, cap: int = DAILY_CAP) -> Decision:
    switch = _SWITCH[kind]
    if switch is not None and not getattr(prefs, switch):
        return Decision(False, "switched_off")
    if prefs.paused_until is not None and now_utc < prefs.paused_until:
        return Decision(False, "paused")
    if in_quiet_hours(local_time(now_utc, prefs).hour, prefs.quiet_start, prefs.quiet_end):
        return Decision(False, "quiet_hours")
    if sent_today >= cap:
        return Decision(False, "daily_cap")
    return Decision(True)


# --- copy ------------------------------------------------------------------
# A few variants per kind, picked by a stable hash so the same event always
# reads the same (and tests can pin it) but a person sees variety over time.

_COPY: dict[Kind, list[tuple[str, str]]] = {
    Kind.FRIEND_SNAP: [
        ("🍜 {name} sent you a snap", "Take a look before it melts away."),
        ("👀 New snap from {name}", "What's on their plate? It's gone in 24 hours."),
        ("📸 {name} is eating something good", "Tap to peek."),
    ],
    Kind.REACTION: [
        ("{emoji} {name} reacted to your snap", "Your plate got noticed."),
        ("{name} sent {emoji}", "Somebody liked what they saw."),
    ],
    Kind.STREAK_AT_RISK: [
        ("🔥 Your {count}-day streak with {name} ends tonight", "One snap keeps it burning."),
        ("⏳ {name} and you: {count} days strong", "Send a snap before midnight to keep it going."),
    ],
    Kind.STREAK_FREEZE: [
        ("🧊 A freeze covered yesterday", "Your {count}-day flame is safe."),
    ],
    Kind.MILESTONE: [
        ("🏅 New badge: {name}", "You earned it. Come and see."),
        ("⭐ Level {count}!", "Every meal you log is paying off."),
    ],
    Kind.MEAL_NUDGE: [
        ("🍽️ Time for a snack snap?", "A photo takes five seconds."),
    ],
}


def copy_for(kind: Kind, key: str, **ctx) -> tuple[str, str]:
    options = _COPY[kind]
    index = int(hashlib.sha256(f"{kind.value}:{key}".encode()).hexdigest(), 16) % len(options)
    title, body = options[index]
    values = {"name": "", "emoji": "", "count": 0}
    values.update(ctx)
    return title.format(**values), body.format(**values)


# --- streak reminders --------------------------------------------------------

# Local hours in which the evening "your streak ends tonight" reminder may go.
# The scheduler runs hourly and the day's dedupe key keeps it to one.
REMINDER_WINDOW = (18, 21)


def in_reminder_window(local_hour: int) -> bool:
    return REMINDER_WINDOW[0] <= local_hour < REMINDER_WINDOW[1]


def pick_streak_to_save(candidates: list[tuple[str, int, bool]]) -> tuple[str, int] | None:
    """[candidates]: (friend name, streak length, I have already sent today).

    The one worth a reminder is a running streak where I still owe a snap.
    With several, the longest wins, then the name, so the choice is stable.
    """
    owed = [(name, count) for name, count, sent_today in candidates if count > 0 and not sent_today]
    if not owed:
        return None
    return sorted(owed, key=lambda c: (-c[1], c[0].lower()))[0]
