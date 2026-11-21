import os

import pytest

# The app's Settings are constructed at import time, so the environment has to
# be in place before anything under app/ is imported.
os.environ.setdefault("USDA_API_KEY", "test-usda")
os.environ.setdefault("GEMINI_API_KEY", "test-gemini")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/test"
)
os.environ.setdefault("CORS_ORIGINS", "http://localhost:3000,https://app.example.com")


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.core.security import get_current_user_id
    from app.main import app

    import uuid

    # A real UUID, as get_current_user_id returns in production. A str here
    # made ownership checks (entry.user_id == user_id) silently mismatch.
    app.dependency_overrides[get_current_user_id] = lambda: uuid.UUID("00000000-0000-0000-0000-000000000001")
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def anon_client():
    """No auth override, so these exercise the real 401 path."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class _Ctx:
    def __init__(self, value=None):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *exc):
        return False


class FakeUsageSession:
    """Stands in for a database session in record_usage: remembers what it ran."""

    def __init__(self, fail=False):
        self.statements = []
        self.fail = fail

    def begin(self):
        return _Ctx()

    def begin_nested(self):
        return _Ctx()

    async def execute(self, stmt):
        if self.fail:
            raise RuntimeError("relation ai_usage does not exist")
        self.statements.append(stmt)


@pytest.fixture(autouse=True)
def usage_db(monkeypatch):
    """No test reaches a real database through the usage counter."""
    from app.core import features

    session = FakeUsageSession()
    monkeypatch.setattr(features, "_new_session", lambda: _Ctx(session))
    return session


@pytest.fixture(autouse=True)
def no_open_food_facts(monkeypatch):
    """No test reaches the real Open Food Facts through the barcode route.
    Tests of the fallback replace this again."""
    from app.routers import foods

    async def nothing(code):
        return None

    monkeypatch.setattr(foods, "lookup_off_barcode", nothing)


@pytest.fixture(autouse=True)
def no_dish_estimates(monkeypatch):
    """No test reaches Gemini through the dish-estimate step of a scan. Tests
    of that step replace this again."""
    from app.routers import photo_estimation

    async def nothing(names, region=None):
        return {}

    monkeypatch.setattr(photo_estimation, "estimate_foods", nothing)


@pytest.fixture(autouse=True)
def fresh_gemini_budget():
    """The Gemini budget and its 429 breaker are process-wide, so every test starts with them clear."""
    from app.core.rate_limit import photo_scans, scans_per_day
    from app.services import gemini_budget, scan_cache

    gemini_budget.reset()
    scan_cache.clear()
    scans_per_day.reset()
    photo_scans.reset()
    yield
    gemini_budget.reset()
    scan_cache.clear()
    scans_per_day.reset()
