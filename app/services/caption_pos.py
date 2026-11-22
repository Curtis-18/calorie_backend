"""Where a caption sits on a bite or story photo.

Best effort on both sides, like the other optional tables: a missing table or a
failed write never stops a photo being sent, and a failed read just means the
caption sits at its default spot.
"""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.caption_pos import SnapCaptionPosition, StoryCaptionPosition

log = logging.getLogger("calorie_backend")


def clean(y: float | None, caption: str | None) -> float | None:
    """A position only means something with a caption, and only between 0 and 1."""
    if y is None or not caption:
        return None
    try:
        y = float(y)
    except (TypeError, ValueError):
        return None
    if y != y or y < 0 or y > 1:  # NaN or off the photo
        return None
    return round(y, 4)


async def save(db: AsyncSession, model, key: str, item_id: uuid.UUID, y: float | None) -> None:
    if y is None:
        return
    try:
        async with db.begin_nested():
            db.add(model(**{key: item_id, "y": y}))
            await db.flush()
    except Exception as exc:  # noqa: BLE001 - the photo matters more than where its words sit
        log.warning("could not save a caption position: %r", exc)


async def load(db: AsyncSession, model, key_column, ids) -> dict[uuid.UUID, float]:
    ids = list(ids)
    if not ids:
        return {}
    try:
        async with db.begin_nested():
            rows = (await db.execute(select(key_column, model.y).where(key_column.in_(ids)))).all()
        return {k: float(y) for k, y in rows}
    except Exception as exc:  # noqa: BLE001
        log.warning("could not read caption positions: %r", exc)
        return {}


async def for_snaps(db: AsyncSession, snaps) -> dict[uuid.UUID, float]:
    """Only asks when something actually has a caption."""
    return await load(db, SnapCaptionPosition, SnapCaptionPosition.snap_id, [s.id for s in snaps if s.caption])


async def for_stories(db: AsyncSession, stories) -> dict[uuid.UUID, float]:
    return await load(db, StoryCaptionPosition, StoryCaptionPosition.story_id, [s.id for s in stories if s.caption])


async def save_snap(db: AsyncSession, snap_id: uuid.UUID, y: float | None, caption: str | None) -> None:
    await save(db, SnapCaptionPosition, "snap_id", snap_id, clean(y, caption))


async def save_story(db: AsyncSession, story_id: uuid.UUID, y: float | None, caption: str | None) -> None:
    await save(db, StoryCaptionPosition, "story_id", story_id, clean(y, caption))
