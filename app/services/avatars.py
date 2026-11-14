"""Profile pictures: where they are stored and the links the app shows.

Photos sit in the private bucket, so the app needs a signed link to show one.
A fresh link on every request would make every phone download every friend's
picture again each time a list refreshed, so links are made to last a day and
reused for half of that.
"""

import logging
import time
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.story import ProfileAvatar
from app.services import storage_service
from app.services.storage_service import StorageUnavailable

log = logging.getLogger("calorie_backend")

LINK_SECONDS = 24 * 3600
REUSE_SECONDS = 12 * 3600
_MAX_CACHED = 5000

# storage path -> (signed link, when to stop handing it out). A new picture
# gets a new path, so a changed photo never shows a stale link.
_links: dict[str, tuple[str, float]] = {}


def forget_links() -> None:
    _links.clear()


async def avatar_paths(db: AsyncSession, ids) -> dict[uuid.UUID, str]:
    """Storage path of each person's picture. Empty if the table isn't there
    yet (migration not run) or the read fails: pictures are never worth
    failing a request for."""
    ids = list(ids)
    if not ids:
        return {}
    try:
        # A savepoint, so a failure here can't poison the caller's transaction.
        async with db.begin_nested():
            rows = (
                await db.execute(
                    select(ProfileAvatar.user_id, ProfileAvatar.storage_path).where(ProfileAvatar.user_id.in_(ids))
                )
            ).all()
    except Exception as exc:  # noqa: BLE001
        log.warning("could not read profile pictures: %r", exc)
        return {}
    return {uid: path for uid, path in rows}


async def links_for(paths: list[str]) -> dict[str, str]:
    now = time.monotonic()
    out = {p: _links[p][0] for p in paths if p in _links and _links[p][1] > now}
    missing = [p for p in dict.fromkeys(paths) if p not in out]
    if missing:
        try:
            signed = await storage_service.sign(missing, expires_in=LINK_SECONDS)
        except StorageUnavailable:
            log.exception("could not sign profile picture links")
            signed = {}
        if len(_links) > _MAX_CACHED:
            for stale in [p for p, (_, until) in _links.items() if until <= now]:
                del _links[stale]
        for path, url in signed.items():
            if url:
                _links[path] = (url, now + REUSE_SECONDS)
                out[path] = url
    return out


async def avatar_urls(db: AsyncSession, ids) -> dict[uuid.UUID, str]:
    """A viewing link for each of [ids] who has a picture."""
    if not storage_service.configured():
        return {}
    paths = await avatar_paths(db, ids)
    if not paths:
        return {}
    links = await links_for(list(paths.values()))
    return {uid: links[p] for uid, p in paths.items() if p in links}
