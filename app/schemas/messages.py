import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

MAX_MESSAGE_CHARS = 1000


class MessageIn(BaseModel):
    id: uuid.UUID = Field(..., description="Chosen by the app so a retry can't send twice")
    body: str = Field(..., max_length=MAX_MESSAGE_CHARS * 2)
    # The earlier message of this conversation being replied to (a quote).
    reply_to: uuid.UUID | None = None

    @field_validator("body")
    @classmethod
    def _not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Write something first.")
        if len(v) > MAX_MESSAGE_CHARS:
            raise ValueError(f"Messages can be at most {MAX_MESSAGE_CHARS} characters.")
        return v


class QuoteOut(BaseModel):
    """What a reply quotes. When the original was unsent, only `deleted` is true:
    the text is gone for everyone."""

    id: uuid.UUID | None = None
    mine: bool | None = None  # whether I wrote the quoted message
    body: str | None = None  # shortened
    deleted: bool = False


class MessageOut(BaseModel):
    id: uuid.UUID
    mine: bool
    body: str
    created_at: datetime
    # For messages I sent: when they opened the conversation ("Seen"). Always
    # null for messages sent to me.
    read_at: datetime | None = None
    # A card shown under the text, e.g. {"kind": "recipe", "id": ..., "title": ..., "calories": ...}.
    # Older apps ignore it and show the text.
    attachment: dict | None = None
    # The message this one replies to. Older apps ignore it.
    quote: QuoteOut | None = None


class ThreadOut(BaseModel):
    messages: list[MessageOut]  # oldest first
    has_more: bool  # older messages exist before the first one returned


class ConversationOut(BaseModel):
    user_id: uuid.UUID
    username: str
    avatar_url: str | None = None
    last_body: str
    last_mine: bool
    last_at: datetime
    unread: int


class ConversationsOut(BaseModel):
    conversations: list[ConversationOut]  # newest first
    unread_total: int
