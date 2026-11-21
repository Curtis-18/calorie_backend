"""Remembers what Gemini saw in a photo for a short while.

A retry after a lost response, or the same photo sent twice, would otherwise
be a second paid call for an identical answer. On the free tier every request
counts, so the answer is kept in memory for an hour, keyed by a hash of the
photo and of everything else that shapes the answer (the note, the region and
the language). Nothing is written to disk and the photo itself is never kept,
only its hash; a restart simply forgets it.
"""

import copy
import hashlib
import time

TTL_SECONDS = 3600
MAX_ENTRIES = 100

_entries: dict[str, tuple[float, list[dict]]] = {}


def key_for(image: bytes, note: str | None, region: str | None, lang: str) -> str:
    digest = hashlib.sha256(image)
    for part in (note or "", region or "", lang):
        digest.update(b"\x00" + part.encode())
    return digest.hexdigest()


def get(key: str, now: float | None = None) -> list[dict] | None:
    now = time.monotonic() if now is None else now
    found = _entries.get(key)
    if found is None:
        return None
    stored_at, items = found
    if now - stored_at > TTL_SECONDS:
        _entries.pop(key, None)
        return None
    return copy.deepcopy(items)


def put(key: str, items: list[dict], now: float | None = None) -> None:
    now = time.monotonic() if now is None else now
    if len(_entries) >= MAX_ENTRIES:
        # Oldest first. A hundred small lists is nothing, so this is simple, not clever.
        for old in sorted(_entries, key=lambda k: _entries[k][0])[: MAX_ENTRIES // 4]:
            _entries.pop(old, None)
    _entries[key] = (now, copy.deepcopy(items))


def clear() -> None:
    _entries.clear()
