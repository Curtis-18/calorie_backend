"""A shared daily budget for Gemini calls, for running on the free tier.

On the free tier Google gives the whole *project* (every user of the key
together) a small number of requests a day, reset at midnight Pacific time. The
per-model number is only visible in Google AI Studio, so it is set by hand in
`GEMINI_DAILY_BUDGET` (0 = no limit of our own). Two things stop the quota from
being wasted:

1. **Priorities.** A call kind may only use its share of the day's budget, so a
   burst of coach messages or Insights refreshes cannot leave nothing for the
   photo scan, which is the headline feature: scan and estimate may use all of
   it, the coach half, Insights a quarter.
2. **A circuit breaker.** After Google answers 429, no further call is sent
   until it can work again (until midnight Pacific when the daily quota is
   spent, otherwise for a short wait). The app then gets an instant, honest
   answer instead of three more doomed attempts.

Everything is kept per model, because Google counts the quota per project *and
per model*: when the main model's day is spent, a configured fallback model
(`GEMINI_FALLBACK_MODEL`) still has its own allowance.

Kept in memory per process: a restart forgets the count (it can only
under-count, and a real 429 still trips the breaker). Pure functions of an
injectable clock, so they are tested without waiting.
"""

import logging
import re
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx

from app.core.config import settings

log = logging.getLogger("calorie_backend")

PACIFIC = ZoneInfo("America/Los_Angeles")

# Share of the daily budget each kind of call may use. Scans come first.
SHARES = {"scan": 1.0, "estimate": 1.0, "coach": 0.5, "insights": 0.25}
DEFAULT_SHARE = 0.5

# A per-minute limit clears quickly; never block for longer than this because
# of one.
MAX_SHORT_BLOCK_SECONDS = 300
DEFAULT_SHORT_BLOCK_SECONDS = 60


class QuotaExhausted(Exception):
    """No Gemini call may be made right now (Google's quota, or our own budget)."""

    def __init__(self, daily: bool = False):
        super().__init__("gemini quota exhausted" + (" for today" if daily else ""))
        self.daily = daily


class _State:
    def __init__(self):
        self.day = None
        self.used = 0
        self.blocked_until: datetime | None = None
        self.blocked_daily = False


_states: dict[str, _State] = {}


def reset() -> None:
    """Forget everything (tests)."""
    _states.clear()


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(timezone.utc)


def _today(now: datetime):
    return now.astimezone(PACIFIC).date()


def _state(model: str | None) -> _State:
    return _states.setdefault(model or settings.gemini_model, _State())


def budget_for(model: str | None) -> int:
    """The daily budget of [model]: the fallback has its own number."""
    model = model or settings.gemini_model
    if settings.gemini_fallback_model and model == settings.gemini_fallback_model != settings.gemini_model:
        return settings.gemini_fallback_daily_budget
    return settings.gemini_daily_budget


def next_reset(now: datetime) -> datetime:
    """The next midnight in Pacific time, when Google's daily quota resets."""
    tomorrow = _today(now) + timedelta(days=1)
    return datetime.combine(tomorrow, time(0, 0), tzinfo=PACIFIC).astimezone(timezone.utc)


def _roll_over(state: _State, now: datetime) -> None:
    if state.day != _today(now):
        state.day = _today(now)
        state.used = 0


def check(kind: str, now: datetime | None = None, model: str | None = None) -> None:
    """Raise QuotaExhausted if a call of this kind must not be made to [model] now."""
    now = _now(now)
    state = _state(model)
    _roll_over(state, now)
    if state.blocked_until is not None:
        if now < state.blocked_until:
            raise QuotaExhausted(daily=state.blocked_daily)
        state.blocked_until, state.blocked_daily = None, False
    budget = budget_for(model)
    if budget > 0 and state.used >= budget * SHARES.get(kind, DEFAULT_SHARE):
        raise QuotaExhausted(daily=True)


def record_call(now: datetime | None = None, model: str | None = None) -> None:
    """Count one call that Gemini answered."""
    state = _state(model)
    _roll_over(state, _now(now))
    state.used += 1


def used_today(now: datetime | None = None, model: str | None = None) -> int:
    state = _state(model)
    _roll_over(state, _now(now))
    return state.used


_RETRY_DELAY = re.compile(r'"retryDelay"\s*:\s*"(\d+(?:\.\d+)?)s"')
_PER_DAY = re.compile(r"per\s*day|PerDay|daily", re.IGNORECASE)


def note_rejected(body: str, now: datetime | None = None, model: str | None = None) -> None:
    """Google answered 429: stop sending until it can work again. A daily limit
    waits for midnight Pacific; anything else for the delay Google names (at
    most a few minutes) or a short default."""
    now = _now(now)
    state = _state(model)
    if _PER_DAY.search(body or ""):
        state.blocked_until, state.blocked_daily = next_reset(now), True
        log.warning("gemini daily quota spent for %s; not calling it again until %s", model or settings.gemini_model, state.blocked_until.isoformat())
        return
    match = _RETRY_DELAY.search(body or "")
    seconds = float(match.group(1)) if match else DEFAULT_SHORT_BLOCK_SECONDS
    seconds = min(max(seconds, 1.0), MAX_SHORT_BLOCK_SECONDS)
    state.blocked_until, state.blocked_daily = now + timedelta(seconds=seconds), False
    log.warning("gemini rate limited on %s; pausing calls to it for %ds", model or settings.gemini_model, seconds)


def is_quota_error(exc: BaseException) -> bool:
    """Whether [exc] means Gemini's quota is spent: our own refusal, or Google's 429."""
    if isinstance(exc, QuotaExhausted):
        return True
    return isinstance(exc, httpx.HTTPStatusError) and exc.response is not None and exc.response.status_code == 429
