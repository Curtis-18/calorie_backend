"""The rules for friend requests, as a pure function.

The router gathers the facts from the database and applies the result; every
decision lives here so it can be tested without one.
"""

import uuid
from dataclasses import dataclass
from enum import Enum

FRIEND_LIMIT = 100
# Stops someone firing requests at everyone they can think of.
PENDING_OUT_LIMIT = 50


class Outcome(str, Enum):
    SEND = "sent"
    ACCEPT = "accepted"  # they had already asked us, so asking back = accepting
    ALREADY_FRIENDS = "already_friends"
    ALREADY_SENT = "already_sent"
    # Errors
    NOT_FOUND = "not_found"
    SELF = "self"
    ME_AT_LIMIT = "me_at_limit"
    THEM_AT_LIMIT = "them_at_limit"
    TOO_MANY_PENDING = "too_many_pending"


@dataclass(frozen=True)
class ExistingLink:
    requester_id: uuid.UUID
    status: str  # 'pending' | 'accepted'


@dataclass(frozen=True)
class RequestFacts:
    me: uuid.UUID
    target: uuid.UUID | None  # None = no such username
    blocked_either_way: bool
    existing: ExistingLink | None
    my_friends: int
    their_friends: int
    my_pending_out: int


def decide_request(f: RequestFacts) -> Outcome:
    # A blocked person looks exactly like a missing one: no hint that either
    # side blocked the other.
    if f.target is None or f.blocked_either_way:
        return Outcome.NOT_FOUND
    if f.target == f.me:
        return Outcome.SELF

    if f.existing is not None:
        if f.existing.status == "accepted":
            return Outcome.ALREADY_FRIENDS
        if f.existing.requester_id == f.me:
            return Outcome.ALREADY_SENT
        # They asked us first: this is an acceptance, which adds a friend to both.
        if f.my_friends >= FRIEND_LIMIT:
            return Outcome.ME_AT_LIMIT
        if f.their_friends >= FRIEND_LIMIT:
            return Outcome.THEM_AT_LIMIT
        return Outcome.ACCEPT

    if f.my_friends >= FRIEND_LIMIT:
        return Outcome.ME_AT_LIMIT
    if f.their_friends >= FRIEND_LIMIT:
        return Outcome.THEM_AT_LIMIT
    if f.my_pending_out >= PENDING_OUT_LIMIT:
        return Outcome.TOO_MANY_PENDING
    return Outcome.SEND


def can_accept(my_friends: int, their_friends: int) -> Outcome | None:
    """The limit that blocks accepting a request, or None if it is fine."""
    if my_friends >= FRIEND_LIMIT:
        return Outcome.ME_AT_LIMIT
    if their_friends >= FRIEND_LIMIT:
        return Outcome.THEM_AT_LIMIT
    return None


MESSAGES = {
    Outcome.NOT_FOUND: "We couldn't find anyone with that username.",
    Outcome.SELF: "That's you! Share your username with a friend instead.",
    Outcome.ME_AT_LIMIT: f"You've reached the limit of {FRIEND_LIMIT} friends. Remove one to add another.",
    Outcome.THEM_AT_LIMIT: "That person has reached their friend limit.",
    Outcome.TOO_MANY_PENDING: "You have a lot of requests waiting. Wait for some to be answered first.",
}
