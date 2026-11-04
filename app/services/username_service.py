"""Username rules, kept pure so they're easy to test exhaustively.

Usernames are how friends find each other (exact match only), so they have
to be easy to type and say aloud: letters, digits and underscores.
"""

import re
from datetime import datetime, timedelta, timezone

MIN_LENGTH = 3
MAX_LENGTH = 20
CHANGE_COOLDOWN = timedelta(days=30)

_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")

# Names that could be mistaken for the app or its staff.
RESERVED = frozenset({
    "admin", "administrator", "moderator", "mod", "support", "help", "staff",
    "team", "official", "nustreak", "nu_streak", "root", "system", "security",
    "null", "undefined", "anonymous", "me", "you", "everyone", "all",
})


def validate_username(raw: str) -> str | None:
    """A user-facing reason the name is not allowed, or None if it is fine."""
    name = raw.strip()
    if len(name) < MIN_LENGTH:
        return f"Usernames need at least {MIN_LENGTH} characters."
    if len(name) > MAX_LENGTH:
        return f"Usernames can be at most {MAX_LENGTH} characters."
    if not name[0].isascii() or not name[0].isalpha():
        return "Usernames must start with a letter."
    if not _PATTERN.match(name):
        return "Use only letters, numbers and underscores."
    if name.endswith("_") or "__" in name:
        return "Underscores can't be doubled or go at the end."
    if name.lower() in RESERVED:
        return "That name isn't available."
    return None


def can_change_at(changed_at: datetime | None, has_username: bool) -> datetime | None:
    """When the user may next change their name, or None if they can now.

    The first pick is always free; after that it's once per cooldown.
    """
    if not has_username or changed_at is None:
        return None
    if changed_at.tzinfo is None:
        changed_at = changed_at.replace(tzinfo=timezone.utc)
    allowed = changed_at + CHANGE_COOLDOWN
    return allowed if allowed > datetime.now(timezone.utc) else None
