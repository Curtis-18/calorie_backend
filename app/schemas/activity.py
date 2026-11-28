import uuid
from datetime import datetime

from pydantic import BaseModel


class ActivityItemOut(BaseModel):
    id: uuid.UUID
    kind: str  # "bite" | "reaction"
    username: str
    emoji: str | None = None
    created_at: datetime
    seen: bool
    # The bite a "bite" line is about (null for reactions); the app opens it
    # if it is still in the inbox. Older apps ignore it.
    snap_id: uuid.UUID | None = None


class ActivityOut(BaseModel):
    items: list[ActivityItemOut]
    unread: int
