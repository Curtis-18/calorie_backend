from datetime import datetime

from pydantic import BaseModel, Field


class UsernameIn(BaseModel):
    username: str = Field(..., max_length=64)


class UsernameCheckOut(BaseModel):
    available: bool
    # Why not, in words the user can act on. None when available.
    reason: str | None = None


class UsernameOut(BaseModel):
    username: str
    can_change_at: datetime | None = None
