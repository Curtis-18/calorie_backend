from fastapi import Header

from app.i18n import parse_language


async def get_language(accept_language: str | None = Header(default=None)) -> str:
    """The language the app is showing, from its Accept-Language header."""
    return parse_language(accept_language)
