import asyncio
import uuid

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient, PyJWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.user import Profile

bearer_scheme = HTTPBearer()
_jwks_client = PyJWKClient(settings.jwks_url, cache_keys=True, lifespan=600)


def _decode(creds: HTTPAuthorizationCredentials) -> dict:
    signing_key = _jwks_client.get_signing_key_from_jwt(creds.credentials)
    return jwt.decode(
        creds.credentials,
        signing_key.key,
        algorithms=["ES256"],
        audience=settings.jwt_audience,
        issuer=f"{settings.supabase_url}/auth/v1",
        options={"require": ["exp", "sub", "aud"]},
    )


async def verify_token(creds: HTTPAuthorizationCredentials = Depends(bearer_scheme)) -> dict:
    try:
        # PyJWKClient does a blocking HTTPS fetch on a cache miss. Off the
        # event loop, otherwise the first request after a cold start stalls
        # every other in-flight request behind it.
        return await asyncio.to_thread(_decode, creds)
    except PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token") from exc


async def get_current_user_id(
    payload: dict = Depends(verify_token),
    db: AsyncSession = Depends(get_db),
) -> uuid.UUID:
    try:
        user_id = uuid.UUID(payload["sub"])
    except (ValueError, KeyError, AttributeError, TypeError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid user ID in token")

    result = await db.execute(select(Profile.id).where(Profile.id == user_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user_not_found")

    return user_id
