"""Remembers the language a person uses the app in, for push notifications.

Both calls run in a savepoint and never raise: before the migration is run, or
if the database hiccups, notifications are simply written in English.
"""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.i18n import DEFAULT, normalize
from app.models.user_language import UserLanguage

log = logging.getLogger("calorie_backend")


async def recall(db: AsyncSession, user_id: uuid.UUID) -> str:
    try:
        async with db.begin_nested():
            row = (await db.execute(select(UserLanguage.language).where(UserLanguage.user_id == user_id))).scalar_one_or_none()
    except Exception:  # noqa: BLE001
        log.warning("user_language unavailable, using English", exc_info=True)
        return DEFAULT
    return normalize(row)


async def remember(db: AsyncSession, user_id: uuid.UUID, language: str) -> bool:
    """True when it was saved. The caller commits."""
    language = normalize(language)
    try:
        async with db.begin_nested():
            await db.execute(
                pg_insert(UserLanguage)
                .values(user_id=user_id, language=language)
                .on_conflict_do_update(index_elements=["user_id"], set_={"language": language})
            )
        return True
    except Exception:  # noqa: BLE001
        log.warning("could not remember the language", exc_info=True)
        return False
