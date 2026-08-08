import uuid
import jwt
from jwt import PyJWKClient, PyJWTError
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.core.config import settings

bearer_scheme = HTTPBearer()
_jwks_client = PyJWKClient(settings.jwks_url, cache_keys=True, lifespan=600)

def verify_token(creds: HTTPAuthorizationCredentials = Depends(bearer_scheme)) -> dict:
    try:
        signing_key = _jwks_client.get_signing_key_from_jwt(creds.credentials)
        return jwt.decode(
            creds.credentials,
            signing_key.key,
            algorithms=["ES256"],
            audience=settings.jwt_audience,
        )
    except PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token") from exc

# CHANGE: Return a uuid.UUID object instead of a string
def get_current_user_id(payload: dict = Depends(verify_token)) -> uuid.UUID:
    try:
        return uuid.UUID(payload["sub"])
    except (ValueError, KeyError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid user ID in token")
