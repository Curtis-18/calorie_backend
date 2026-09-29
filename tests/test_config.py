import pytest

from app.core.config import Settings

BASE = {
    "usda_api_key": "x",
    "gemini_api_key": "x",
    "supabase_url": "https://x.supabase.co",
}


def make(database_url, **extra):
    return Settings(_env_file=None, database_url=database_url, **{**BASE, **extra})


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("postgresql://u:p@h:5432/db", "postgresql+asyncpg://u:p@h:5432/db"),
        ("postgres://u:p@h:5432/db", "postgresql+asyncpg://u:p@h:5432/db"),
        ("postgresql+psycopg2://u:p@h/db", "postgresql+asyncpg://u:p@h/db"),
        ("postgresql+psycopg://u:p@h/db", "postgresql+asyncpg://u:p@h/db"),
        ("postgresql+asyncpg://u:p@h/db", "postgresql+asyncpg://u:p@h/db"),
        (
            "postgresql://u:p@h:6543/db?sslmode=require",
            "postgresql+asyncpg://u:p@h:6543/db?sslmode=require",
        ),
    ],
)
def test_database_url_always_speaks_asyncpg(raw, expected):
    """A bare postgresql:// from a dashboard must not become 'No module named psycopg'."""
    assert make(raw).database_url == expected


def test_database_url_is_stripped():
    assert make("  postgresql://u:p@h/db  ").database_url == "postgresql+asyncpg://u:p@h/db"


def test_supabase_url_trailing_slash_stripped():
    """jwks_url would otherwise become .../auth/v1//.well-known/jwks.json."""
    s = make("postgresql://u:p@h/db", supabase_url="https://x.supabase.co/")
    assert s.supabase_url == "https://x.supabase.co"
    assert s.jwks_url == "https://x.supabase.co/auth/v1/.well-known/jwks.json"


def test_cors_origins_are_a_list():
    s = make("postgresql://u:p@h/db", cors_origins="https://a.com, https://b.com ,")
    assert s.allowed_origins == ["https://a.com", "https://b.com"]


def test_missing_required_secret_fails_loudly(monkeypatch):
    """A half-configured deploy must fail on boot, not on the first request."""
    from pydantic import ValidationError

    for var in ("USDA_API_KEY", "GEMINI_API_KEY", "SUPABASE_URL", "DATABASE_URL"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
