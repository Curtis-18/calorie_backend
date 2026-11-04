import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.services.username_service import can_change_at, validate_username

ME = uuid.UUID("00000000-0000-0000-0000-000000000001")
OTHER = uuid.UUID("00000000-0000-0000-0000-000000000002")


@pytest.mark.parametrize("name", ["sam", "Sam_99", "a1b", "x" * 20, "  sam  ", "river_song"])
def test_good_usernames(name):
    assert validate_username(name) is None


@pytest.mark.parametrize("name", [
    "", "ab", "x" * 21, "1sam", "_sam", "sam_", "sa__m", "sa m", "sam!", "sam-jones",
    "sämi", "😀😀😀", "Admin", "NUSTREAK", "support",
])
def test_bad_usernames(name):
    assert validate_username(name)  # a reason is returned


def test_first_pick_is_free_then_one_change_per_30_days():
    now = datetime.now(timezone.utc)
    assert can_change_at(None, has_username=False) is None
    assert can_change_at(now - timedelta(days=1), has_username=False) is None
    assert can_change_at(now - timedelta(days=1), has_username=True) is not None
    assert can_change_at(now - timedelta(days=31), has_username=True) is None
    # a naive timestamp from the DB is treated as UTC rather than crashing
    assert can_change_at((now - timedelta(days=31)).replace(tzinfo=None), True) is None


class _Result:
    def __init__(self, value=None, row=None):
        self.value, self.row = value, row

    def scalar_one_or_none(self):
        return self.value

    def one(self):
        return self.row


class _Db:
    """Scripted session: each execute() pops the next result."""

    def __init__(self, *results, commit_error=None):
        self.results = list(results)
        self.commit_error = commit_error
        self.committed = self.rolled_back = False
        self.writes = 0

    async def execute(self, stmt):
        if str(stmt).lstrip().upper().startswith("UPDATE"):
            self.writes += 1
            return _Result()
        return self.results.pop(0)

    async def commit(self):
        if self.commit_error:
            raise self.commit_error
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


def _with_db(db):
    from app.core.database import get_db
    from app.main import app

    async def fake_db():
        yield db

    app.dependency_overrides[get_db] = fake_db


def test_check_reports_format_problems_without_touching_the_db(client):
    _with_db(_Db())
    r = client.get("/username/check", params={"name": "1sam"})
    assert r.json() == {"available": False, "reason": "Usernames must start with a letter."}


def test_check_taken_free_and_own(client):
    _with_db(_Db(_Result(OTHER)))
    assert client.get("/username/check", params={"name": "sam"}).json()["available"] is False
    _with_db(_Db(_Result(None)))
    assert client.get("/username/check", params={"name": "sam"}).json() == {"available": True, "reason": None}
    _with_db(_Db(_Result(ME)))  # my own current name is fine
    assert client.get("/username/check", params={"name": "sam"}).json()["available"] is True


def test_first_pick_succeeds(client):
    db = _Db(_Result(row=(None, None)), _Result(None))
    _with_db(db)
    r = client.post("/username", json={"username": "Sam_99"})
    assert r.status_code == 200
    body = r.json()
    assert body["username"] == "Sam_99" and body["can_change_at"] is not None
    assert db.committed and db.writes == 1


def test_invalid_name_is_422(client):
    _with_db(_Db())
    r = client.post("/username", json={"username": "a"})
    assert r.status_code == 422 and "at least 3" in r.json()["detail"]


def test_taken_name_is_409(client):
    _with_db(_Db(_Result(row=(None, None)), _Result(OTHER)))
    r = client.post("/username", json={"username": "sam"})
    assert r.status_code == 409 and r.json()["detail"] == "That username is taken."


def test_losing_a_race_is_409_not_500(client):
    db = _Db(_Result(row=(None, None)), _Result(None),
             commit_error=IntegrityError("x", {}, Exception("dup")))
    _with_db(db)
    r = client.post("/username", json={"username": "sam"})
    assert r.status_code == 409 and db.rolled_back


def test_change_inside_the_cooldown_is_429(client):
    recent = datetime.now(timezone.utc) - timedelta(days=3)
    _with_db(_Db(_Result(row=("old_name", recent))))
    r = client.post("/username", json={"username": "new_name"})
    assert r.status_code == 429 and "again on" in r.json()["detail"]


def test_change_after_the_cooldown_works(client):
    old = datetime.now(timezone.utc) - timedelta(days=40)
    db = _Db(_Result(row=("old_name", old)), _Result(None))
    _with_db(db)
    assert client.post("/username", json={"username": "new_name"}).status_code == 200
    assert db.committed


def test_retry_with_the_same_name_is_a_no_op(client):
    recent = datetime.now(timezone.utc) - timedelta(minutes=1)
    db = _Db(_Result(row=("sam", recent)))
    _with_db(db)
    r = client.post("/username", json={"username": "sam"})
    assert r.status_code == 200 and db.writes == 0


def test_recapitalising_your_own_name_is_free_during_cooldown(client):
    recent = datetime.now(timezone.utc) - timedelta(days=2)
    db = _Db(_Result(row=("sam", recent)))
    _with_db(db)
    r = client.post("/username", json={"username": "SAM"})
    assert r.status_code == 200 and db.writes == 1


def test_me_returns_the_username(client):
    _with_db(_Db(_Result("sam")))
    assert client.get("/me").json() == {"user_id": str(ME), "username": "sam"}


def test_me_survives_a_missing_column(client):
    class Boom:
        async def execute(self, _):
            raise RuntimeError('column "username" does not exist')

    _with_db(Boom())
    assert client.get("/me").json() == {"user_id": str(ME), "username": None}
