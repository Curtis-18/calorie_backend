"""Deleting an account for good (App Store guideline 5.1.1(v), Google Play's
account deletion rule).

Everything a person owns hangs off their `auth.users` row: `profiles` cascades
from it, and every app table cascades from `profiles`. So deleting that one row
removes their food logs, targets, weigh-ins, friendships, blocks, bites,
notification settings and device tokens. The only thing the database can't
remove is the photos in storage (bites, stories, profile picture), which go first.
"""

import logging
import uuid

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import auth_users
from app.models.snap import Snap
from app.models.story import ProfileAvatar, Story
from app.models.user import Profile
from app.services import storage_service

log = logging.getLogger("calorie_backend")


class AccountDeletionFailed(Exception):
    pass


async def _delete_auth_user_via_api(user_id: uuid.UUID) -> None:
    """Supabase's admin API: the supported way, which also ends the person's
    sessions. Needs the service role key."""
    key = settings.supabase_service_role_key
    url = f"{settings.supabase_url}/auth/v1/admin/users/{user_id}"
    try:
        async with httpx.AsyncClient() as client:
            r = await client.delete(url, headers={"Authorization": f"Bearer {key}", "apikey": key}, timeout=20.0)
    except httpx.HTTPError as exc:
        raise AccountDeletionFailed(f"auth delete failed: {exc!r}") from exc
    # 404 = already gone (a retry after a lost response): that is the goal.
    if r.status_code >= 300 and r.status_code != 404:
        log.error("auth delete %s: %s", r.status_code, r.text[:300])
        raise AccountDeletionFailed(f"auth delete failed with {r.status_code}")


async def _optional_paths(db: AsyncSession, query) -> list[str]:
    """Photo paths from a table that may not exist yet (stories and profile
    pictures arrived in a later migration). A savepoint keeps a missing table
    from poisoning the transaction."""
    try:
        async with db.begin_nested():
            return list((await db.execute(query)).scalars().all())
    except Exception as exc:  # noqa: BLE001
        log.warning("skipping optional photo cleanup: %r", exc)
        return []


async def delete_account(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Remove the person and everything they own. Raises AccountDeletionFailed
    with nothing deleted from the database if a step can't be completed, so
    the app can simply ask them to try again."""
    # 1. Bite, story and profile photos. Once the rows are gone nothing would ever find these
    #    files again, so a failure here stops the deletion rather than leaving
    #    someone's photos behind.
    if storage_service.configured():
        paths = list((await db.execute(select(Snap.storage_path).where(Snap.sender_id == user_id))).scalars().all())
        paths += await _optional_paths(db, select(Story.storage_path).where(Story.user_id == user_id))
        paths += await _optional_paths(db, select(ProfileAvatar.storage_path).where(ProfileAvatar.user_id == user_id))
        if paths:
            try:
                await storage_service.delete(paths)
            except storage_service.StorageUnavailable as exc:
                raise AccountDeletionFailed(f"photo cleanup failed: {exc!r}") from exc

    # 2. The login itself, which cascades to every table.
    if settings.supabase_service_role_key:
        await _delete_auth_user_via_api(user_id)
    else:
        # No service key on this deployment: the backend's own database role
        # can remove the row directly.
        try:
            await db.execute(delete(auth_users).where(auth_users.c.id == user_id))
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            raise AccountDeletionFailed(f"auth row delete failed: {exc!r}") from exc

    # 3. Belt and braces: the profile row should already be gone through the
    #    cascade. If this project's foreign key was ever created without it,
    #    this still removes the person's data.
    try:
        await db.execute(delete(Profile).where(Profile.id == user_id))
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        raise AccountDeletionFailed(f"profile delete failed: {exc!r}") from exc
