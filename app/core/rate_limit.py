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

    def check(self, name: str, user_id: uuid.UUID, message: str) -> None:
        if not self.allow(name, user_id):
            raise HTTPException(status_code=429, detail=message)

    def reset(self) -> None:
        self._hits.clear()


photo_scans = RateLimit(30, 3600)
insight_generations = RateLimit(30, 3600)
food_searches = RateLimit(90, 60)
