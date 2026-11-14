import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class StoryIn(BaseModel):
    id: uuid.UUID = Field(..., description="Chosen by the app so a retry can't post twice")
    image: str = Field(..., description="Base64 JPEG, PNG or WebP")
    caption: str | None = Field(None, max_length=120)


class StoryPostedOut(BaseModel):
    story_id: uuid.UUID
    expires_at: datetime


class StoryOut(BaseModel):
    """A friend's story, as you see it."""

    story_id: uuid.UUID
    caption: str | None
    created_at: datetime
    expires_at: datetime
    image_url: str | None  # None if a link couldn't be made; the app shows a placeholder
    viewed: bool
    reaction: str | None  # your reaction to it


class ViewerOut(BaseModel):
    user_id: uuid.UUID
    username: str
    avatar_url: str | None = None
    reaction: str | None


class MyStoryOut(BaseModel):
    story_id: uuid.UUID
    caption: str | None
    created_at: datetime
    expires_at: datetime
    image_url: str | None
    viewers: list[ViewerOut]


class FriendStoriesOut(BaseModel):
    user_id: uuid.UUID
    username: str
    avatar_url: str | None = None
    streak: int = 0
    all_seen: bool
    stories: list[StoryOut]  # oldest first, the order they play in


class StoryFeedOut(BaseModel):
    mine: list[MyStoryOut]
    friends: list[FriendStoriesOut]


class AvatarIn(BaseModel):
    image: str = Field(..., description="Base64 JPEG, PNG or WebP")


class AvatarOut(BaseModel):
    avatar_url: str | None
