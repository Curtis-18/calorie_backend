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
