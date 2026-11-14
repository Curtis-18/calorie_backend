"""Direct messages between friends."""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.schemas.messages import MessageIn

ME = uuid.UUID("00000000-0000-0000-0000-000000000001")
SAM = uuid.UUID("00000000-0000-0000-0000-000000000002")
BEA = uuid.UUID("00000000-0000-0000-0000-000000000003")
NOW = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)


class _Result:
    def __init__(self, value=None, rows=None, rowcount=1):
        self.value, self.rows, self.rowcount = value, rows or [], rowcount

    def scalar_one_or_none(self):
        return self.value

    def scalars(self):
        return SimpleNamespace(all=lambda: self.rows)

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None


class _Db:
    def __init__(self, *results):
        self.results = list(results)
        self.statements, self.added = [], []
        self.committed = self.rolled_back = False

    async def execute(self, stmt):
        self.statements.append(stmt)
        return self.results.pop(0)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


def _with_db(db):
    from app.core.database import get_db
    from app.main import app

    async def fake_db():
        yield db

    app.dependency_overrides[get_db] = fake_db


@pytest.fixture(autouse=True)
def _fresh_limits():
    from app.core.rate_limit import messages_sent

    messages_sent.reset()
    yield
    messages_sent.reset()


def _msg(sender, recipient, body="hi", minutes=0, read=False, mid=None):
    from app.models.message import Message

    return Message(
        id=mid or uuid.uuid4(), sender_id=sender, recipient_id=recipient, body=body,
        created_at=NOW + timedelta(minutes=minutes), read_at=NOW if read else None,
    )


FRIENDS = _Result(rows=[(ME, SAM)])  # the friendship row
FRIEND = _Result(rows=[(uuid.uuid4(),)])  # "are we friends?" found one
NOT_FRIEND = _Result(rows=[])


# --- what may be written -----------------------------------------------------

def test_a_message_is_trimmed_and_must_say_something():
    assert MessageIn(id=uuid.uuid4(), body="  hello  ").body == "hello"
    with pytest.raises(ValidationError):
        MessageIn(id=uuid.uuid4(), body="   \n ")
    with pytest.raises(ValidationError):
        MessageIn(id=uuid.uuid4(), body="x" * 1001)
    assert len(MessageIn(id=uuid.uuid4(), body="x" * 1000).body) == 1000


# --- sending -----------------------------------------------------------------

def test_a_friend_can_be_sent_a_message(client):
    db = _Db(_Result(None), FRIEND)
    _with_db(db)
    mid = uuid.uuid4()
    r = client.post(f"/messages/with/{SAM}", json={"id": str(mid), "body": " hey! "})
    assert r.status_code == 200
    out = r.json()
    assert (out["id"], out["mine"], out["body"], out["read_at"]) == (str(mid), True, "hey!", None)
    assert db.committed
    saved = db.added[0]
    assert (saved.sender_id, saved.recipient_id, saved.body) == (ME, SAM, "hey!")


def test_strangers_cannot_be_messaged(client):
    db = _Db(_Result(None), NOT_FRIEND)
    _with_db(db)
    r = client.post(f"/messages/with/{BEA}", json={"id": str(uuid.uuid4()), "body": "hi"})
    assert r.status_code == 403 and not db.added


def test_you_cannot_message_yourself(client):
    _with_db(_Db(_Result(None)))
    assert client.post(f"/messages/with/{ME}", json={"id": str(uuid.uuid4()), "body": "hi"}).status_code == 422


def test_empty_and_oversized_messages_are_refused(client):
    _with_db(_Db())
    assert client.post(f"/messages/with/{SAM}", json={"id": str(uuid.uuid4()), "body": "  "}).status_code == 422
    assert client.post(f"/messages/with/{SAM}", json={"id": str(uuid.uuid4()), "body": "x" * 1001}).status_code == 422


def test_retrying_the_same_id_returns_the_original(client):
    mid = uuid.uuid4()
    db = _Db(_Result(_msg(ME, SAM, "first", mid=mid)))
    _with_db(db)
    r = client.post(f"/messages/with/{SAM}", json={"id": str(mid), "body": "first"})
    assert r.status_code == 200 and r.json()["body"] == "first"
    assert not db.added and not db.committed


def test_someone_elses_message_id_is_not_reusable(client):
    mid = uuid.uuid4()
    _with_db(_Db(_Result(_msg(SAM, ME, "theirs", mid=mid))))
    assert client.post(f"/messages/with/{SAM}", json={"id": str(mid), "body": "x"}).status_code == 409
    # Even my own id, if it went to a different person.
    _with_db(_Db(_Result(_msg(ME, BEA, "other chat", mid=mid))))
    assert client.post(f"/messages/with/{SAM}", json={"id": str(mid), "body": "x"}).status_code == 409


def test_sending_too_fast_is_slowed_down(client):
    from app.core.rate_limit import messages_sent

    for _ in range(messages_sent.limit):
        assert messages_sent.allow("message", ME)
    _with_db(_Db(_Result(None), FRIEND))
    r = client.post(f"/messages/with/{SAM}", json={"id": str(uuid.uuid4()), "body": "hi"})
    assert r.status_code == 429


def test_two_sends_with_one_id_at_once_keep_the_first(client):
    from sqlalchemy.exc import IntegrityError

    mid = uuid.uuid4()

    class Race(_Db):
        async def commit(self):
            raise IntegrityError("insert", {}, Exception("duplicate"))

    db = Race(_Result(None), FRIEND, _Result(_msg(ME, SAM, "winner", mid=mid)))
    _with_db(db)
    r = client.post(f"/messages/with/{SAM}", json={"id": str(mid), "body": "winner"})
    assert r.status_code == 200 and r.json()["body"] == "winner" and db.rolled_back


# --- reading -----------------------------------------------------------------

def test_a_conversation_is_oldest_first_and_only_shows_seen_on_mine(client):
    newest_first = [
        _msg(SAM, ME, "c", minutes=3),
        _msg(ME, SAM, "b", minutes=2, read=True),
        _msg(SAM, ME, "a", minutes=1, read=True),  # their message: read_at must not leak
    ]
    _with_db(_Db(FRIEND, _Result(rows=newest_first)))
    r = client.get(f"/messages/with/{SAM}")
    assert r.status_code == 200
    out = r.json()
    assert [m["body"] for m in out["messages"]] == ["a", "b", "c"]
    assert [m["mine"] for m in out["messages"]] == [False, True, False]
    assert [m["read_at"] is not None for m in out["messages"]] == [False, True, False]
    assert out["has_more"] is False


def test_a_long_conversation_says_there_is_more(client):
    rows = [_msg(SAM, ME, str(i), minutes=100 - i) for i in range(3)]  # limit 2 -> 3 fetched
    _with_db(_Db(FRIEND, _Result(rows=rows)))
    out = client.get(f"/messages/with/{SAM}?limit=2").json()
    assert out["has_more"] is True and len(out["messages"]) == 2


def test_the_conversation_with_a_non_friend_is_closed(client):
    _with_db(_Db(NOT_FRIEND))
    assert client.get(f"/messages/with/{BEA}").status_code == 403


def test_the_paging_cursor_and_limit_are_checked(client):
    _with_db(_Db())
    assert client.get(f"/messages/with/{SAM}?limit=0").status_code == 422
    assert client.get(f"/messages/with/{SAM}?limit=101").status_code == 422
    assert client.get(f"/messages/with/{SAM}?before=yesterday").status_code == 422


def test_opening_a_conversation_marks_theirs_as_read(client):
    db = _Db(_Result())
    _with_db(db)
    assert client.post(f"/messages/with/{SAM}/read").status_code == 204
    assert db.committed
    sql = str(db.statements[0].compile(compile_kwargs={"literal_binds": False}))
    assert sql.startswith("UPDATE messages SET read_at=")
    assert "messages.sender_id" in sql and "messages.read_at IS NULL" in sql


# --- the list ----------------------------------------------------------------

@pytest.fixture
def pictures(monkeypatch):
    from app.services import avatars

    async def fake(db, ids):
        return {SAM: "https://img/sam.jpg"}

    monkeypatch.setattr(avatars, "avatar_urls", fake)


def test_the_conversation_list_has_last_message_and_unread_counts(client, pictures):
    db = _Db(
        _Result(rows=[(ME, SAM), (BEA, ME)]),  # my friends
        _Result(rows=[
            (SAM, "Sam", "see you", ME, NOW + timedelta(minutes=5)),
            (BEA, "Bea", "lunch?", BEA, NOW + timedelta(minutes=9)),
        ]),
        _Result(rows=[(BEA, 2)]),
    )
    _with_db(db)
    out = client.get("/messages").json()
    assert [c["username"] for c in out["conversations"]] == ["Bea", "Sam"]  # newest first
    bea, sam = out["conversations"]
    assert (bea["unread"], bea["last_mine"], bea["last_body"], bea["avatar_url"]) == (2, False, "lunch?", None)
    assert (sam["unread"], sam["last_mine"], sam["avatar_url"]) == (0, True, "https://img/sam.jpg")
    assert out["unread_total"] == 2


def test_no_friends_means_no_conversations_and_no_more_queries(client):
    db = _Db(_Result(rows=[]))
    _with_db(db)
    assert client.get("/messages").json() == {"conversations": [], "unread_total": 0}
    assert len(db.statements) == 1


def test_the_list_only_covers_current_friends_in_one_query(client, pictures):
    db = _Db(_Result(rows=[(ME, SAM)]), _Result(rows=[]), _Result(rows=[]))
    _with_db(db)
    client.get("/messages")
    from sqlalchemy.dialects import postgresql

    sql = str(db.statements[1].compile(dialect=postgresql.dialect()))
    assert "DISTINCT ON" in sql and "JOIN profiles" in sql and " IN " in sql


# --- unsend and report -------------------------------------------------------

def test_you_can_unsend_only_your_own_message(client):
    db = _Db(_Result(rowcount=1))
    _with_db(db)
    assert client.delete(f"/messages/{uuid.uuid4()}").status_code == 204 and db.committed
    sql = str(db.statements[0].compile())
    assert "sender_id" in sql

    db = _Db(_Result(rowcount=0))
    _with_db(db)
    assert client.delete(f"/messages/{uuid.uuid4()}").status_code == 404 and not db.committed


def test_reporting_keeps_the_text_in_case_it_is_unsent_later(client):
    mid = uuid.uuid4()
    db = _Db(_Result(_msg(SAM, ME, "something rude", mid=mid)))
    _with_db(db)
    r = client.post(f"/messages/{mid}/report", json={"reason": "abuse"})
    assert r.status_code == 204 and db.committed
    report = db.added[0]
    assert (report.kind, report.reported_user_id, report.reporter_id, report.subject_id) == ("message", SAM, ME, mid)
    assert "abuse" in report.reason and "something rude" in report.reason


def test_you_can_only_report_a_message_sent_to_you(client):
    _with_db(_Db(_Result(None)))
    assert client.post(f"/messages/{uuid.uuid4()}/report", json={}).status_code == 404


def test_signed_out_people_get_nothing(anon_client):
    assert anon_client.get("/messages").status_code in (401, 403)
    assert anon_client.post(f"/messages/with/{SAM}", json={"id": str(uuid.uuid4()), "body": "x"}).status_code in (401, 403)


def test_the_migration_widens_the_report_kinds_and_turns_on_rls():
    sql = open("migrations/2026-11-14_messages.sql").read()
    assert "'message'" in sql and "content_reports_kind_check" in sql
    assert "enable row level security" in sql
