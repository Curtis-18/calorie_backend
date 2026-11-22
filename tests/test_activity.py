"""The in-app Notifications list: bites and reactions from friends."""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services import activity

ME = uuid.UUID("00000000-0000-0000-0000-000000000001")
SAM = uuid.UUID("00000000-0000-0000-0000-000000000002")
NOW = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc)


class _Result:
    def __init__(self, rows=None, scalar=None):
        self.rows, self.scalar = rows or [], scalar

    def all(self):
        return self.rows

    def scalar_one_or_none(self):
        return self.scalar


class _Nested:
    def __init__(self, fail=False):
        self.fail = fail

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _Db:
    def __init__(self, *results, fail_on=None):
        self.results, self.statements = list(results), []
        self.committed = self.rolled_back = False
        self.fail_on = fail_on

    def begin_nested(self):
        return _Nested()

    async def execute(self, stmt):
        self.statements.append(str(stmt))
        if self.fail_on is not None and len(self.statements) == self.fail_on:
            raise RuntimeError("relation \"activity\" does not exist")
        return self.results.pop(0)

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


def row(kind="bite", emoji=None, seen=False, who="sam", minutes=0):
    return SimpleNamespace(id=uuid.uuid4(), kind=kind, emoji=emoji, created_at=NOW - timedelta(minutes=minutes),
                           seen_at=NOW if seen else None, username=who)


# --- reading ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_list_has_the_lines_and_the_unseen_count():
    out = await activity.feed(_Db(_Result(rows=[row("reaction", "🔥", who="bea"), row(seen=True, minutes=5)]), _Result(scalar=1)), ME, now=NOW)
    assert out["unread"] == 1
    assert [(i["kind"], i["username"], i["emoji"], i["seen"]) for i in out["items"]] == [
        ("reaction", "bea", "🔥", False),
        ("bite", "sam", None, True),
    ]


@pytest.mark.asyncio
async def test_a_missing_table_is_an_empty_list_not_an_error():
    assert await activity.feed(_Db(fail_on=1), ME, now=NOW) == {"items": [], "unread": 0}


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [None, "x", -3])
async def test_a_strange_count_is_zero(value):
    out = await activity.feed(_Db(_Result(rows=[]), _Result(scalar=value)), ME, now=NOW)
    assert out["unread"] == 0


@pytest.mark.asyncio
async def test_a_line_whose_person_has_no_name_still_loads():
    out = await activity.feed(_Db(_Result(rows=[row(who=None)]), _Result(scalar=1)), ME, now=NOW)
    assert out["items"][0]["username"] == ""


@pytest.mark.asyncio
async def test_the_list_only_reads_the_last_month_and_hides_blocked_people():
    db = _Db(_Result(rows=[]), _Result(scalar=0))
    await activity.feed(db, ME, now=NOW)
    sql = db.statements[0]
    assert "blocks" in sql and "created_at >=" in sql and "LIMIT" in sql


# --- marking as seen -----------------------------------------------------------

@pytest.mark.asyncio
async def test_opening_the_list_marks_everything_seen_and_tidies_old_lines():
    db = _Db(_Result(), _Result())
    await activity.mark_seen(db, ME, now=NOW)
    assert db.statements[0].startswith("UPDATE activity") and db.statements[1].startswith("DELETE FROM activity")
    assert db.committed


@pytest.mark.asyncio
async def test_marking_seen_never_raises():
    db = _Db(fail_on=1)
    await activity.mark_seen(db, ME, now=NOW)
    assert db.rolled_back


# --- writing -------------------------------------------------------------------

@pytest.mark.asyncio
async def test_nothing_is_recorded_for_yourself_or_for_messages_and_requests():
    assert await activity.record(ME, "bite", ME) is False
    for kind in ("message", "friend_request", "friend_accepted", ""):
        assert await activity.record(SAM, kind, ME) is False
    assert activity.KINDS == ("bite", "reaction")


@pytest.mark.asyncio
async def test_recording_never_raises(monkeypatch):
    class Broken:
        async def __aenter__(self):
            raise RuntimeError("db down")

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(activity, "async_session_maker", lambda: Broken())
    assert await activity.record(SAM, "bite", ME, dedupe_key="k") is False


@pytest.mark.asyncio
async def test_a_new_line_is_added_once_and_a_repeat_adds_nothing(monkeypatch):
    class Session:
        def __init__(self):
            self.committed = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def execute(self, stmt):
            text = str(stmt)
            assert "ON CONFLICT DO NOTHING" in text and "RETURNING" in text
            return _Result(scalar=next(answers))

        async def commit(self):
            self.committed = True

    answers = iter([uuid.uuid4(), None])
    monkeypatch.setattr(activity, "async_session_maker", lambda: Session())
    assert await activity.record(SAM, "reaction", ME, emoji="🔥", dedupe_key="react:1") is True
    assert await activity.record(SAM, "reaction", ME, emoji="🔥", dedupe_key="react:1") is False


# --- the routes ----------------------------------------------------------------

def _with_db(db):
    from app.core.database import get_db
    from app.main import app

    async def fake_db():
        yield db

    app.dependency_overrides[get_db] = fake_db


def test_the_route_returns_the_list(client):
    _with_db(_Db(_Result(rows=[row("reaction", "🔥", who="bea")]), _Result(scalar=1)))
    r = client.get("/activity")
    assert r.status_code == 200
    body = r.json()
    assert body["unread"] == 1 and body["items"][0]["kind"] == "reaction" and body["items"][0]["username"] == "bea"
    assert set(body["items"][0]) == {"id", "kind", "username", "emoji", "created_at", "seen"}


def test_opening_marks_seen_and_answers_204(client):
    db = _Db(_Result(), _Result())
    _with_db(db)
    assert client.post("/activity/seen").status_code == 204 and db.committed


def test_the_routes_need_a_login():
    from fastapi.testclient import TestClient
    from app.main import app

    app.dependency_overrides.clear()
    c = TestClient(app)
    assert c.get("/activity").status_code in (401, 403)
    assert c.post("/activity/seen").status_code in (401, 403)
