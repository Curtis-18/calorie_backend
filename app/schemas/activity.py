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


class ActivityOut(BaseModel):
    items: list[ActivityItemOut]
    unread: int
