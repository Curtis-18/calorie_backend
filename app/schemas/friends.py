import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class FriendRequestIn(BaseModel):
    username: str = Field(..., max_length=64)


class PersonOut(BaseModel):
    """Someone on the other end of a friendship, request or block."""

    # The friendship row's id (or, for blocks, empty): what the app sends back
    # to accept, decline, remove or block.
    friendship_id: uuid.UUID | None = None
    user_id: uuid.UUID
    username: str
    since: datetime


class FriendsOut(BaseModel):
    friends: list[PersonOut]
    incoming: list[PersonOut]
    outgoing: list[PersonOut]
    limit: int


class RequestResultOut(BaseModel):
    # sent | accepted | already_friends | already_sent
    outcome: str
    username: str
