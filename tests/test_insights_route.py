import uuid
from datetime import date as date_type, datetime, timedelta, timezone

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

    async def fake_trend(db, user_id, today):
        return _trend()

    async def fake_generate(db, user_id, trend, today, lang="en"):
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
    out = await insights_router.get_insights(user_id=uuid.uuid4(), db=db, lang="en")

    assert isinstance(out, InsightsOut)
    assert out.narrative == "hi"
    assert db.rolled_back is True


async def test_cached_insights_report_an_explicit_utc_offset(monkeypatch):
    async def boom(*args, **kwargs):
        raise AssertionError("cache hit should short-circuit generation")

    monkeypatch.setattr(insights_router, "generate_insights", boom)

    async def same_trend(db, user_id, today):
        return _trend()

    monkeypatch.setattr(insights_router, "get_weekly_trend", same_trend)

    class Cached:
        # The server's "today" is UTC; date.today() is the machine's local date
        # and differs near midnight away from UTC.
        date = datetime.now(timezone.utc).date()
        payload = {"narrative": "cached", "tips": [], "weekly_trend": _trend()}
        generated_at = datetime(2026, 10, 11, 10, 24, 5)  # naive, as read back

    class _Result:
        def scalar_one_or_none(self):
            return Cached()

    class FakeDb:
        async def execute(self, stmt):
            return _Result()

    out = await insights_router.get_insights(
        refresh=False, user_id=uuid.uuid4(), db=FakeDb(), lang="en"
    )
    assert out.generated_at.tzinfo is not None


async def test_a_meal_logged_after_the_first_visit_regenerates_the_narrative(monkeypatch):
    """The cached narrative said "no meals today" all day, even after logging."""
    fresh = _trend()
    fresh[-1] = {**fresh[-1], "calories": fresh[-1]["calories"] + 450}
    generated = []

    async def new_trend(db, user_id, today):
        return fresh

    async def new_insights(db, user_id, trend, today, lang="en"):
        generated.append(trend)
        return {"narrative": "you logged a meal", "tips": [], "weekly_trend": trend}

    monkeypatch.setattr(insights_router, "get_weekly_trend", new_trend)
    monkeypatch.setattr(insights_router, "generate_insights", new_insights)

    class Cached:
        date = datetime.now(timezone.utc).date()
        payload = {"narrative": "no meals yet", "tips": [], "weekly_trend": _trend()}
        generated_at = datetime(2026, 10, 11, 10, 24, 5)

    class _Result:
        def scalar_one_or_none(self):
            return Cached()

    class FakeDb:
        async def execute(self, stmt):
            return _Result()

        async def commit(self):
            pass

        async def rollback(self):
            pass

    out = await insights_router.get_insights(refresh=False, user_id=uuid.uuid4(), db=FakeDb(), lang="en")
    assert generated == [fresh]
    assert out.narrative == "you logged a meal"


def test_resolve_today_defaults_to_the_utc_date_for_older_clients():
    from app.routers.insights import resolve_today

    assert resolve_today(None) == datetime.now(timezone.utc).date()


def test_resolve_today_accepts_any_real_timezone_and_rejects_the_rest():
    from datetime import timedelta

    import pytest
    from fastapi import HTTPException

    from app.routers.insights import resolve_today

    utc_today = datetime.now(timezone.utc).date()
    for offset in (-1, 0, 1):  # UTC-12 .. UTC+14 is always within a day
        d = utc_today + timedelta(days=offset)
        assert resolve_today(d) == d
    for offset in (-2, 2, 400):
        with pytest.raises(HTTPException) as exc:
            resolve_today(utc_today + timedelta(days=offset))
        assert exc.value.status_code == 422


async def test_insights_use_the_device_date_for_trend_prompt_and_cache(monkeypatch):
    """At 01:00 in Nairobi (UTC+3) the device is already on the next day while
    the server's UTC date is still the previous one. The week, the "today"
    numbers and the cache must follow the device."""
    from datetime import timedelta

    device_today = datetime.now(timezone.utc).date() + timedelta(days=1)
    seen = {}

    async def fake_trend(db, user_id, today):
        seen["trend_today"] = today
        return _trend()

    async def fake_generate(db, user_id, trend, today, lang="en"):
        seen["generate_today"] = today
        return {"narrative": "hi", "tips": [], "weekly_trend": trend}

    monkeypatch.setattr(insights_router, "get_weekly_trend", fake_trend)
    monkeypatch.setattr(insights_router, "generate_insights", fake_generate)

    class StaleCache:  # cached under the UTC date: must not count as today's
        date = device_today - timedelta(days=1)
        payload = {"narrative": "stale", "tips": [], "weekly_trend": _trend()}
        generated_at = datetime(2026, 11, 1, 22, 0, 0)

    class _Result:
        def scalar_one_or_none(self):
            return StaleCache()

    class FakeDb:
        def __init__(self):
            self.upserts = []

        async def execute(self, stmt):
            if hasattr(stmt, "compile") and "INSERT" in str(stmt).upper():
                self.upserts.append(stmt.compile().params)
                return None
            return _Result()

        async def commit(self):
            pass

        async def rollback(self):
            pass

    db = FakeDb()
    out = await insights_router.get_insights(
        refresh=False, date=device_today, user_id=uuid.uuid4(), db=db, lang="en"
    )

    assert out.narrative == "hi"
    assert seen == {"trend_today": device_today, "generate_today": device_today}
    assert db.upserts and db.upserts[0]["date"] == device_today


def test_insights_rejects_an_implausible_date_over_http(client):
    r = client.get("/insights", params={"date": "2001-01-01"})
    assert r.status_code == 422


async def test_logging_a_food_does_not_call_gemini_while_the_narrative_is_fresh(monkeypatch):
    """The app reloads Insights after every logged food; that used to be one
    paid call each. Now the cached text is served with the live chart."""
    from datetime import timedelta

    fresh = _trend()
    fresh[-1] = {**fresh[-1], "calories": 450}

    async def new_trend(db, user_id, today):
        return fresh

    async def boom(*args, **kwargs):
        raise AssertionError("must not call Gemini")

    monkeypatch.setattr(insights_router, "get_weekly_trend", new_trend)
    monkeypatch.setattr(insights_router, "generate_insights", boom)

    class Cached:
        date = datetime.now(timezone.utc).date()
        payload = {"narrative": "earlier text", "tips": ["t"], "weekly_trend": _trend()}
        generated_at = _utcnow_naive() - timedelta(minutes=20)

    class _Result:
        def scalar_one_or_none(self):
            return Cached()

    class FakeDb:
        async def execute(self, stmt):
            return _Result()

    out = await insights_router.get_insights(refresh=False, user_id=uuid.uuid4(), db=FakeDb(), lang="en")
    assert out.narrative == "earlier text"
    assert out.weekly_trend[-1].calories == 450  # the chart is live


async def test_a_pull_to_refresh_still_regenerates_a_fresh_narrative(monkeypatch):
    from datetime import timedelta

    called = []

    async def trend(db, user_id, today):
        return _trend()

    async def new_insights(db, user_id, t, today, lang="en"):
        called.append(1)
        return {"narrative": "new", "tips": [], "weekly_trend": t}

    monkeypatch.setattr(insights_router, "get_weekly_trend", trend)
    monkeypatch.setattr(insights_router, "generate_insights", new_insights)
    insights_router.insight_generations.reset()

    class Cached:
        date = datetime.now(timezone.utc).date()
        payload = {"narrative": "old", "tips": [], "weekly_trend": _trend()}
        generated_at = _utcnow_naive() - timedelta(minutes=5)

    class _Result:
        def scalar_one_or_none(self):
            return Cached()

    class FakeDb:
        async def execute(self, stmt):
            return _Result()

        async def commit(self):
            pass

        async def rollback(self):
            pass

    out = await insights_router.get_insights(refresh=True, user_id=uuid.uuid4(), db=FakeDb(), lang="en")
    assert called and out.narrative == "new"


async def test_only_a_real_generation_is_counted_not_a_cache_hit(monkeypatch):
    from fastapi import BackgroundTasks

    async def trend(db, user_id, today):
        return _trend()

    async def new_insights(db, user_id, t, today, lang="en"):
        return {"narrative": "new", "tips": [], "weekly_trend": t}

    monkeypatch.setattr(insights_router, "get_weekly_trend", trend)
    monkeypatch.setattr(insights_router, "generate_insights", new_insights)
    insights_router.insight_generations.reset()

    class _Result:
        def __init__(self, cached):
            self.cached = cached

        def scalar_one_or_none(self):
            return self.cached

    class FakeDb:
        def __init__(self, cached):
            self.cached = cached

        async def execute(self, stmt):
            return _Result(self.cached)

        async def commit(self):
            pass

        async def rollback(self):
            pass

    # No cache: one generation, one counted use of INSIGHTS.
    tasks = BackgroundTasks()
    await insights_router.get_insights(refresh=False, background=tasks, user_id=uuid.uuid4(), db=FakeDb(None), lang="en")
    assert [t.args[1] for t in tasks.tasks] == [insights_router.Feature.INSIGHTS]

    # Fresh cache: served as is, nothing counted.
    class Cached:
        date = datetime.now(timezone.utc).date()
        payload = {"narrative": "old", "tips": [], "weekly_trend": _trend()}
        generated_at = _utcnow_naive()

    tasks = BackgroundTasks()
    out = await insights_router.get_insights(refresh=False, background=tasks, user_id=uuid.uuid4(), db=FakeDb(Cached()), lang="en")
    assert out.narrative == "old" and tasks.tasks == []


# ---- targets changed after the narrative was written ----------------------------------------------------------

class _Nested:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _db_with(cached, targets_updated_at):
    """First read: the cache row; the targets read: [targets_updated_at]."""

    class _Result:
        def __init__(self, value):
            self.value = value

        def scalar_one_or_none(self):
            return self.value

    class FakeDb:
        async def execute(self, stmt):
            if "targets" in str(stmt):
                return _Result(targets_updated_at)
            return _Result(cached)

        def begin_nested(self):
            return _Nested()

        async def commit(self):
            pass

        async def rollback(self):
            pass

    return FakeDb()


def _cached(generated_at):
    class Cached:
        date = datetime.now(timezone.utc).date()
        payload = {"narrative": "old targets", "tips": [], "weekly_trend": _trend()}

    Cached.generated_at = generated_at
    return Cached()


async def test_targets_changed_since_compares_with_when_the_text_was_written():
    written = datetime(2026, 11, 22, 8, 0, 0)  # naive UTC, as read back
    uid = uuid.uuid4()
    later = datetime(2026, 11, 22, 9, 0, 0, tzinfo=timezone.utc)
    earlier = datetime(2026, 11, 22, 7, 0, 0, tzinfo=timezone.utc)
    assert await insights_router._targets_changed_since(_db_with(None, later), uid, written) is True
    assert await insights_router._targets_changed_since(_db_with(None, earlier), uid, written) is False
    assert await insights_router._targets_changed_since(_db_with(None, None), uid, written) is False


async def test_a_database_error_reading_targets_never_breaks_insights():
    class Broken:
        def begin_nested(self):
            return _Nested()

        async def execute(self, stmt):
            raise RuntimeError("boom")

    assert await insights_router._targets_changed_since(Broken(), uuid.uuid4(), datetime(2026, 11, 22)) is False


async def test_new_targets_make_the_cached_narrative_stale(monkeypatch):
    generated = []

    async def same_trend(db, user_id, today):
        return _trend()

    async def new_insights(db, user_id, trend, today, lang="en"):
        generated.append(1)
        return {"narrative": "new targets", "tips": [], "weekly_trend": trend, "language": lang}

    monkeypatch.setattr(insights_router, "get_weekly_trend", same_trend)
    monkeypatch.setattr(insights_router, "generate_insights", new_insights)

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    # Text written a minute ago; targets saved 10 seconds ago.
    db = _db_with(_cached(now - timedelta(minutes=1)), (now - timedelta(seconds=10)).replace(tzinfo=timezone.utc))
    out = await insights_router.get_insights(user_id=uuid.uuid4(), db=db, lang="en")
    assert generated == [1] and out.narrative == "new targets"


async def test_unchanged_targets_keep_serving_the_cached_narrative(monkeypatch):
    async def same_trend(db, user_id, today):
        return _trend()

    async def boom(*a, **k):
        raise AssertionError("must not regenerate")

    monkeypatch.setattr(insights_router, "get_weekly_trend", same_trend)
    monkeypatch.setattr(insights_router, "generate_insights", boom)

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db = _db_with(_cached(now - timedelta(minutes=1)), (now - timedelta(hours=5)).replace(tzinfo=timezone.utc))
    out = await insights_router.get_insights(user_id=uuid.uuid4(), db=db, lang="en")
    assert out.narrative == "old targets"
