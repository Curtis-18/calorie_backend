"""A small per-person rate limit for the endpoints that cost money.

Photo scans and insights call Gemini, and food search uses a USDA key with an
hourly quota shared by everyone. Without a limit one signed-in account (or a
stolen token) could run up the bill or lock every other user out of search.

Kept in memory, per process: with two workers a person can get up to twice
the stated number, which is fine for a guard against abuse. The limits are
far above what the app itself does.
"""

import time
import uuid
from collections import deque

from fastapi import HTTPException

_MAX_TRACKED = 20000


class RateLimit:
    def __init__(self, limit: int, per_seconds: float):
        self.limit = limit
        self.per_seconds = per_seconds
        self._hits: dict[tuple[str, uuid.UUID], deque[float]] = {}

    def allow(self, name: str, user_id: uuid.UUID, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        cutoff = now - self.per_seconds
        if len(self._hits) > _MAX_TRACKED:
            for key in [k for k, hits in self._hits.items() if not hits or hits[-1] <= cutoff]:
                del self._hits[key]
        hits = self._hits.setdefault((name, user_id), deque())
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        return True

    def has_room(self, name: str, user_id: uuid.UUID, now: float | None = None) -> bool:
        """Whether one more is allowed, without counting it. For limits that
        should only count successes (a failed scan must not use up the day)."""
        now = time.monotonic() if now is None else now
        cutoff = now - self.per_seconds
        hits = self._hits.get((name, user_id))
        if not hits:
            return True
        return sum(1 for h in hits if h > cutoff) < self.limit

    def record(self, name: str, user_id: uuid.UUID, now: float | None = None) -> None:
        """Count one, whether or not it was within the limit."""
        now = time.monotonic() if now is None else now
        self._hits.setdefault((name, user_id), deque()).append(now)

    def check(self, name: str, user_id: uuid.UUID, message: str) -> None:
        if not self.allow(name, user_id):
            raise HTTPException(status_code=429, detail=message)

    def reset(self) -> None:
        self._hits.clear()


photo_scans = RateLimit(20, 3600)
# Successful scans per person per day, for running on a small shared free quota.
# The size is read from settings when used (SCANS_PER_USER_PER_DAY, 0 = off).
scans_per_day = RateLimit(1, 86400)
insight_generations = RateLimit(6, 3600)
food_searches = RateLimit(90, 60)
# Typing a name fires a lookup per pause; this is far above that, and stops a
# script walking the alphabet to list every username.
people_searches = RateLimit(60, 60)
messages_sent = RateLimit(60, 60)
# Every coach turn is a paid Gemini call. A daily free allowance joins this in P6.
coach_turns = RateLimit(20, 3600)
# "Send me a test notification" in Settings.
push_tests = RateLimit(5, 3600)
