import uuid
from datetime import date as date_type, datetime

from pydantic import BaseModel, Field

# The only reactions a friend can send: a small, friendly set.
REACTIONS = ("🔥", "😋", "😮", "❤️", "👏")


class SnapIn(BaseModel):
    id: uuid.UUID = Field(..., description="Chosen by the app so a retry can't send twice")
    image: str = Field(..., description="Base64 JPEG, PNG or WebP")
    caption: str | None = Field(None, max_length=120)
    recipient_ids: list[uuid.UUID] = Field(..., min_length=1, max_length=20)
    date: date_type | None = None  # the sender's device-local date


class RecipientOut(BaseModel):
    user_id: uuid.UUID
    username: str
    streak: int
    # True when this snap just completed today's pair (both have now sent):
    # the app plays the flame animation.
    completed_today: bool


class SnapSentOut(BaseModel):
    snap_id: uuid.UUID
    expires_at: datetime
    recipients: list[RecipientOut]


class InboxSnapOut(BaseModel):
    snap_id: uuid.UUID
    sender_id: uuid.UUID
    sender_username: str
    caption: str | None
    created_at: datetime
    expires_at: datetime
    viewed: bool
    reaction: str | None
    image_url: str | None  # None if a link couldn't be made; the app shows a placeholder


class SentRecipientOut(BaseModel):
    user_id: uuid.UUID
    username: str
    viewed: bool
    reaction: str | None


class SentSnapOut(BaseModel):
    snap_id: uuid.UUID
    caption: str | None
    created_at: datetime
    expires_at: datetime
    image_url: str | None
    recipients: list[SentRecipientOut]


class ReactIn(BaseModel):
    emoji: str = Field(..., max_length=8)


class ReportIn(BaseModel):
    reason: str | None = Field(None, max_length=200)
