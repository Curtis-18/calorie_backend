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


def test_trailing_slash_on_an_origin_is_dropped():
    """A browser never sends one, so a pasted URL with one matches nothing."""
    s = make("postgresql://u:p@h/db", cors_origins="https://app.vercel.app/")
    assert s.allowed_origins == ["https://app.vercel.app"]


def test_trailing_slash_on_a_wildcard_is_dropped():
    s = make("postgresql://u:p@h/db", cors_origins="https://app-*.vercel.app/")
    import re

    assert re.compile(s.cors_origin_regex).fullmatch("https://app-a1b2.vercel.app")


def test_no_wildcards_means_no_regex():
    s = make("postgresql://u:p@h/db", cors_origins="https://a.com,https://b.com")
    assert s.cors_origin_regex is None
    assert s.exact_origins == ["https://a.com", "https://b.com"]


def test_wildcard_entries_leave_the_exact_list():
    """A literal entry can never match a preview subdomain, so keep it out."""
    s = make(
        "postgresql://u:p@h/db",
        cors_origins="https://a.com,https://app-*.vercel.app",
    )
    assert s.exact_origins == ["https://a.com"]
    assert s.cors_origin_regex is not None


def test_wildcards_become_one_alternation():
    s = make(
        "postgresql://u:p@h/db",
        cors_origins="https://app-*.vercel.app,https://*.example.com",
    )
    # Starlette fullmatches a single pattern, so both wildcards are joined.
    assert s.cors_origin_regex == r"https://app\-[^/]+\.vercel\.app|https://[^/]+\.example\.com"


@pytest.mark.parametrize(
    "origin,matches",
    [
        ("https://app-a1b2.vercel.app", True),
        ("https://app-a1b2-curtis.vercel.app", True),
        ("http://app-a1b2.vercel.app", False),  # scheme is not a wildcard
        ("https://other.vercel.app", False),
        ("https://app-a1b2.vercel.app.evil.test", False),
        ("https://app-a1b2.vercel.app/extra", False),
        ("https://evil.test/?x=https://app-a1b2.vercel.app", False),
    ],
)
def test_wildcard_regex_accepts_previews_and_nothing_else(origin, matches):
    """`https://app-*.vercel.app` must not become an open door to any origin."""
    import re

    s = make("postgresql://u:p@h/db", cors_origins="https://app-*.vercel.app")
    pattern = re.compile(s.cors_origin_regex)
    assert bool(pattern.fullmatch(origin)) is matches


def test_missing_required_secret_fails_loudly(monkeypatch):
    """A half-configured deploy must fail on boot, not on the first request."""
    from pydantic import ValidationError

    for var in ("USDA_API_KEY", "GEMINI_API_KEY", "SUPABASE_URL", "DATABASE_URL"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
