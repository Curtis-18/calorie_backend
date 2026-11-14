import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from app.services.friends_service import (
    FRIEND_LIMIT,
    PENDING_OUT_LIMIT,
    ExistingLink,
    Outcome,
    RequestFacts,
    can_accept,
    decide_request,
)

ME = uuid.UUID("00000000-0000-0000-0000-000000000001")
SAM = uuid.UUID("00000000-0000-0000-0000-000000000002")


def facts(**kw):
    base = dict(me=ME, target=SAM, blocked_either_way=False, existing=None,
                my_friends=0, their_friends=0, my_pending_out=0)
    base.update(kw)
    return RequestFacts(**base)


# --- the rules -------------------------------------------------------------

def test_a_plain_request_is_sent():
    assert decide_request(facts()) == Outcome.SEND


def test_unknown_username_and_blocked_look_identical():
    assert decide_request(facts(target=None)) == Outcome.NOT_FOUND
    assert decide_request(facts(blocked_either_way=True)) == Outcome.NOT_FOUND


def test_cannot_add_yourself():
    assert decide_request(facts(target=ME)) == Outcome.SELF


def test_repeating_a_request_or_adding_a_friend_is_harmless():
    assert decide_request(facts(existing=ExistingLink(ME, "pending"))) == Outcome.ALREADY_SENT
    assert decide_request(facts(existing=ExistingLink(SAM, "accepted"))) == Outcome.ALREADY_FRIENDS
    assert decide_request(facts(existing=ExistingLink(ME, "accepted"))) == Outcome.ALREADY_FRIENDS


def test_asking_someone_who_already_asked_you_accepts():
    assert decide_request(facts(existing=ExistingLink(SAM, "pending"))) == Outcome.ACCEPT


def test_the_friend_limit_applies_to_both_people_and_to_accepting():
    assert decide_request(facts(my_friends=FRIEND_LIMIT - 1)) == Outcome.SEND
    assert decide_request(facts(my_friends=FRIEND_LIMIT)) == Outcome.ME_AT_LIMIT
    assert decide_request(facts(their_friends=FRIEND_LIMIT)) == Outcome.THEM_AT_LIMIT
    pending_from_them = ExistingLink(SAM, "pending")
    assert decide_request(facts(existing=pending_from_them, my_friends=FRIEND_LIMIT)) == Outcome.ME_AT_LIMIT
    assert decide_request(facts(existing=pending_from_them, their_friends=FRIEND_LIMIT)) == Outcome.THEM_AT_LIMIT


def test_cannot_have_too_many_requests_waiting():
    assert decide_request(facts(my_pending_out=PENDING_OUT_LIMIT - 1)) == Outcome.SEND
    assert decide_request(facts(my_pending_out=PENDING_OUT_LIMIT)) == Outcome.TOO_MANY_PENDING


def test_can_accept_checks_both_sides():
    assert can_accept(5, 5) is None
    assert can_accept(FRIEND_LIMIT, 5) == Outcome.ME_AT_LIMIT
    assert can_accept(5, FRIEND_LIMIT) == Outcome.THEM_AT_LIMIT


def test_the_cap_is_one_hundred():
    assert FRIEND_LIMIT == 100


# --- the endpoints ---------------------------------------------------------

class _Result:
    def __init__(self, value=None, rowcount=1, rows=None):
        self.value, self.rowcount, self.rows = value, rowcount, rows or []

    def scalar_one_or_none(self):
        return self.value

    def scalar_one(self):
        return self.value

    def scalars(self):
        return SimpleNamespace(all=lambda: self.rows)

    def all(self):
        return self.rows


class _Db:
    """Scripted session: each execute() pops the next result and records the statement."""

    def __init__(self, *results, commit_error=None):
        self.results = list(results)
        self.statements = []
        self.added = []
        self.commit_error = commit_error
        self.committed = self.rolled_back = False

    async def execute(self, stmt):
        self.statements.append(str(stmt).split()[0].upper())
        return self.results.pop(0)

    def add(self, obj):
        self.added.append(obj)

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


def _gathered(monkeypatch, f, link=None, name="sam"):
    from app.routers import friends

    async def fake(db, me, username):
        return f, link, name

    monkeypatch.setattr(friends, "_gather", fake)


def test_sending_a_request_stores_it(client, monkeypatch):
    db = _Db()
    _with_db(db)
    _gathered(monkeypatch, facts())
    r = client.post("/friends/requests", json={"username": "Sam"})
    assert r.status_code == 200
    assert r.json() == {"outcome": "sent", "username": "sam"}
    assert len(db.added) == 1 and db.committed
    assert (db.added[0].requester_id, db.added[0].addressee_id) == (ME, SAM)


def test_asking_back_accepts_their_request(client, monkeypatch):
    db = _Db(_Result())
    _with_db(db)
    link = SimpleNamespace(id=uuid.uuid4())
    _gathered(monkeypatch, facts(existing=ExistingLink(SAM, "pending")), link)
    r = client.post("/friends/requests", json={"username": "sam"})
    assert r.json()["outcome"] == "accepted"
    assert db.statements == ["UPDATE"] and db.committed and not db.added


@pytest.mark.parametrize("f,status", [
    (facts(target=None), 404),
    (facts(blocked_either_way=True), 404),
    (facts(target=ME), 422),
    (facts(my_friends=FRIEND_LIMIT), 409),
    (facts(their_friends=FRIEND_LIMIT), 409),
    (facts(my_pending_out=PENDING_OUT_LIMIT), 429),
])
def test_refused_requests_write_nothing(client, monkeypatch, f, status):
    db = _Db()
    _with_db(db)
    _gathered(monkeypatch, f)
    r = client.post("/friends/requests", json={"username": "sam"})
    assert r.status_code == status and r.json()["detail"]
    assert not db.added and not db.committed


def test_repeats_do_not_write_again(client, monkeypatch):
    db = _Db()
    _with_db(db)
    _gathered(monkeypatch, facts(existing=ExistingLink(ME, "pending")))
    assert client.post("/friends/requests", json={"username": "sam"}).json()["outcome"] == "already_sent"
    assert not db.added and not db.committed


def test_a_simultaneous_request_is_a_clean_409(client, monkeypatch):
    db = _Db(commit_error=IntegrityError("x", {}, Exception("dup")))
    _with_db(db)
    _gathered(monkeypatch, facts())
    r = client.post("/friends/requests", json={"username": "sam"})
    assert r.status_code == 409 and db.rolled_back


def test_a_user_without_a_username_cannot_send(client):
    db = _Db(_Result(None))  # my own username lookup
    _with_db(db)
    r = client.post("/friends/requests", json={"username": "sam"})
    assert r.status_code == 409 and "username" in r.json()["detail"]


def test_accepting(client):
    fid = uuid.uuid4()
    row = SimpleNamespace(requester_id=SAM)
    db = _Db(_Result(row), _Result(3), _Result(4), _Result())
    _with_db(db)
    assert client.post(f"/friends/requests/{fid}/accept").status_code == 204
    assert db.statements[-1] == "UPDATE" and db.committed


def test_accepting_someone_elses_or_a_missing_request_is_404(client):
    _with_db(_Db(_Result(None)))
    assert client.post(f"/friends/requests/{uuid.uuid4()}/accept").status_code == 404


def test_accepting_at_the_limit_is_refused(client):
    db = _Db(_Result(SimpleNamespace(requester_id=SAM)), _Result(FRIEND_LIMIT), _Result(1))
    _with_db(db)
    r = client.post(f"/friends/requests/{uuid.uuid4()}/accept")
    assert r.status_code == 409 and not db.committed


def test_declining_and_removing(client):
    _with_db(_Db(_Result(rowcount=1)))
    assert client.post(f"/friends/requests/{uuid.uuid4()}/decline").status_code == 204
    _with_db(_Db(_Result(rowcount=0)))
    assert client.post(f"/friends/requests/{uuid.uuid4()}/decline").status_code == 404
    _with_db(_Db(_Result(rowcount=1)))
    assert client.delete(f"/friends/{uuid.uuid4()}").status_code == 204
    _with_db(_Db(_Result(rowcount=0)))
    assert client.delete(f"/friends/{uuid.uuid4()}").status_code == 404


def test_blocking_removes_the_friendship_and_records_the_block(client):
    row = SimpleNamespace(requester_id=SAM, addressee_id=ME)
    db = _Db(_Result(row), _Result(), _Result())
    _with_db(db)
    assert client.post(f"/friends/{uuid.uuid4()}/block").status_code == 204
    assert db.statements == ["SELECT", "DELETE", "INSERT"] and db.committed


def test_blocking_a_stranger_is_404(client):
    _with_db(_Db(_Result(None)))
    assert client.post(f"/friends/{uuid.uuid4()}/block").status_code == 404


def test_unblock(client):
    _with_db(_Db(_Result(rowcount=1)))
    assert client.delete(f"/blocks/{SAM}").status_code == 204
    _with_db(_Db(_Result(rowcount=0)))
    assert client.delete(f"/blocks/{SAM}").status_code == 404


def test_listing_sorts_into_friends_incoming_and_outgoing(client):
    t = datetime(2026, 11, 4, tzinfo=timezone.utc)
    A, B, C = (uuid.UUID(f"00000000-0000-0000-0000-00000000000{i}") for i in (3, 4, 5))

    def row(requester, addressee, status):
        return SimpleNamespace(id=uuid.uuid4(), requester_id=requester, addressee_id=addressee,
                               status=status, created_at=t, responded_at=t if status == "accepted" else None)

    rows = [row(ME, A, "accepted"), row(B, ME, "pending"), row(ME, C, "pending")]
    db = _Db(_Result(rows=rows), _Result(rows=[(A, "zed"), (B, "Bea"), (C, "cam")]))
    _with_db(db)
    body = client.get("/friends").json()
    assert [p["username"] for p in body["friends"]] == ["zed"]
    assert [p["username"] for p in body["incoming"]] == ["Bea"]
    assert [p["username"] for p in body["outgoing"]] == ["cam"]
    assert body["limit"] == 100


def test_an_empty_list(client):
    _with_db(_Db(_Result(rows=[])))
    assert client.get("/friends").json() == {"friends": [], "incoming": [], "outgoing": [], "limit": 100}


def test_friend_routes_need_a_login(anon_client):
    for method, path in [("get", "/friends"), ("post", "/friends/requests"), ("get", "/blocks")]:
        assert getattr(anon_client, method)(path).status_code in (401, 403)


# --- search as you type ------------------------------------------------------

def test_search_prefix_needs_two_valid_characters():
    from app.services.friends_service import search_prefix

    assert search_prefix(" @Sa ") == "sa"
    assert search_prefix("river_s") == "river_s"
    assert search_prefix("s") is None  # one letter would list a slice of everyone
    assert search_prefix("") is None
    assert search_prefix("sam%") is None
    assert search_prefix("1bad") is None
    assert search_prefix("_x") is None
    assert search_prefix("a b") is None
    assert search_prefix("x" * 21) is None


def test_relation_to_reads_from_my_side():
    from app.services.friends_service import relation_to

    assert relation_to(ME, None, None) == "none"
    assert relation_to(ME, SAM, "accepted") == "friend"
    assert relation_to(ME, ME, "pending") == "requested"
    assert relation_to(ME, SAM, "pending") == "wants_you"


def test_search_returns_matches_with_how_they_stand_in_one_query(client, monkeypatch):
    from app.core.rate_limit import people_searches
    from app.services import avatars, storage_service

    people_searches.reset()
    signed = []

    async def links_for(paths):
        signed.append(paths)
        return {p: f"https://pics/{p}" for p in paths}

    monkeypatch.setattr(avatars, "links_for", links_for)
    monkeypatch.setattr(storage_service, "configured", lambda: True)
    bea = uuid.uuid4()
    db = _Db(
        _Result(rows=[
            (SAM, "Sam", ME, "pending", None),  # I already asked Sam
            (bea, "Sammy", None, None, "bea/avatar-1.jpg"),
        ]),
    )
    _with_db(db)
    r = client.get("/friends/search", params={"q": "@sa"})
    assert r.status_code == 200
    assert [(p["username"], p["relation"], p["avatar_url"]) for p in r.json()] == [
        ("Sam", "requested", None),
        ("Sammy", "none", "https://pics/bea/avatar-1.jpg"),
    ]
    assert db.statements == ["SELECT"]  # one round trip, not three
    assert signed == [["bea/avatar-1.jpg"]]


def test_search_without_pictures_never_calls_storage(client, monkeypatch):
    from app.core.rate_limit import people_searches
    from app.services import avatars

    people_searches.reset()

    async def boom(paths):
        raise AssertionError("no pictures to sign")

    monkeypatch.setattr(avatars, "links_for", boom)
    _with_db(_Db(_Result(rows=[(SAM, "Sam", SAM, "accepted", None)])))
    r = client.get("/friends/search", params={"q": "sa"})
    assert [(p["username"], p["relation"]) for p in r.json()] == [("Sam", "friend")]


def test_search_still_answers_when_pictures_fail(client, monkeypatch):
    from app.core.rate_limit import people_searches
    from app.services import avatars, storage_service

    people_searches.reset()

    async def boom(paths):
        raise RuntimeError("storage down")

    monkeypatch.setattr(avatars, "links_for", boom)
    monkeypatch.setattr(storage_service, "configured", lambda: True)
    _with_db(_Db(_Result(rows=[(SAM, "Sam", None, None, "sam/avatar-1.jpg")])))
    r = client.get("/friends/search", params={"q": "sa"})
    assert r.status_code == 200
    assert r.json()[0]["username"] == "Sam" and r.json()[0]["avatar_url"] is None


def test_search_ignores_what_cannot_match_without_touching_the_database(client):
    db = _Db()
    _with_db(db)
    for q in ["", "s", "sam!", "%%"]:
        assert client.get("/friends/search", params={"q": q}).json() == []
    assert db.statements == []


def test_search_with_no_match_is_an_empty_list(client):
    from app.core.rate_limit import people_searches

    people_searches.reset()
    _with_db(_Db(_Result(rows=[])))
    assert client.get("/friends/search", params={"q": "zz"}).json() == []


def test_search_escapes_underscore_and_excludes_me_and_blocked(client, monkeypatch):
    """The statement itself: "_" must not act as a wildcard, and the filter
    for yourself and for blocks in either direction must be in the query."""
    from app.core.rate_limit import people_searches

    people_searches.reset()
    seen = []

    class Db(_Db):
        async def execute(self, stmt):
            seen.append(stmt)
            return await super().execute(stmt)

    _with_db(Db(_Result(rows=[])))
    client.get("/friends/search", params={"q": "a_b"})
    sql = str(seen[0].compile(compile_kwargs={"literal_binds": True}))
    assert "a/_b" in sql and "ESCAPE '/'" in sql
    assert "NOT (EXISTS" in sql and "blocks" in sql
    assert "profiles.id != " in sql
    assert "LIMIT 8" in sql
    assert "LEFT OUTER JOIN friendships" in sql and "LEFT OUTER JOIN profile_avatars" in sql


def test_search_is_rate_limited(client):
    from app.core.rate_limit import people_searches

    people_searches.reset()
    _with_db(_Db(*[_Result(rows=[]) for _ in range(60)]))
    for _ in range(60):
        assert client.get("/friends/search", params={"q": "sa"}).status_code == 200
    assert client.get("/friends/search", params={"q": "sa"}).status_code == 429
    people_searches.reset()


def test_search_needs_a_signed_in_user(anon_client):
    assert anon_client.get("/friends/search", params={"q": "sa"}).status_code in (401, 403)
