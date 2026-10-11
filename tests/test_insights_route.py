import uuid
from datetime import date as date_type, datetime, timezone

from app.routers import insights as insights_router
from app.routers.insights import _as_utc, _utcnow_naive
from app.schemas.insights import InsightsOut


def test_utcnow_naive_has_no_tzinfo():
    """The insights_cache column is TIMESTAMP WITHOUT TIME ZONE; asyncpg
    rejects an aware datetime bound to it."""
    assert _utcnow_naive().tzinfo is None


def test_as_utc_attaches_timezone_to_naive_values():
    naive = datetime(2026, 10, 11, 10, 24, 5)
    assert _as_utc(naive) == naive.replace(tzinfo=timezone.utc)


def test_as_utc_leaves_aware_values_alone():
    aware = datetime(2026, 10, 11, 10, 24, 5, tzinfo=timezone.utc)
    assert _as_utc(aware) is aware


def _trend():
    return [
        {"date": "2026-10-11", "calories": 0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0}
    ]


async def test_insights_survive_a_cache_write_failure(monkeypatch):
    """A failed upsert (e.g. the aware/naive bind error) must not 500 the
    request once the analysis itself succeeded."""

    async def fake_trend(db, user_id):
        return _trend()

    async def fake_generate(db, user_id, trend):
        return {"narrative": "hi", "tips": ["a"], "weekly_trend": trend}

    monkeypatch.setattr(insights_router, "get_weekly_trend", fake_trend)
    monkeypatch.setattr(insights_router, "generate_insights", fake_generate)

    class _Result:
        def scalar_one_or_none(self):
            return None

    class FakeDb:
        def __init__(self):
            self.calls = 0
            self.rolled_back = False

        async def execute(self, stmt):
            self.calls += 1
            if self.calls == 1:
                return _Result()
            raise RuntimeError("can't subtract offset-naive and offset-aware datetimes")

        async def commit(self):
            pass

        async def rollback(self):
            self.rolled_back = True

    db = FakeDb()
    out = await insights_router.get_insights(user_id=uuid.uuid4(), db=db)

    assert isinstance(out, InsightsOut)
    assert out.narrative == "hi"
    assert db.rolled_back is True


async def test_cached_insights_report_an_explicit_utc_offset(monkeypatch):
    async def boom(*args, **kwargs):
        raise AssertionError("cache hit should short-circuit generation")

    monkeypatch.setattr(insights_router, "generate_insights", boom)

    class Cached:
        date = date_type.today()
        payload = {"narrative": "cached", "tips": [], "weekly_trend": _trend()}
        generated_at = datetime(2026, 10, 11, 10, 24, 5)  # naive, as read back

    class _Result:
        def scalar_one_or_none(self):
            return Cached()

    class FakeDb:
        async def execute(self, stmt):
            return _Result()

    out = await insights_router.get_insights(
        refresh=False, user_id=uuid.uuid4(), db=FakeDb()
    )
    assert out.generated_at.tzinfo is not None
