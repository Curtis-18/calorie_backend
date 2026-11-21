"""Replying to (quoting) a specific message."""

import uuid
from types import SimpleNamespace

import pytest

from app.routers import messages as router
from tests.test_messages import ME, SAM, FRIEND, _Db, _Result, _msg, _with_db


class _Savepoint:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _QuoteDb(_Db):
    """A fake db that also supports savepoints and flush, as the quote code uses them."""

    def __init__(self, *results, fail_quote_insert=False):
        super().__init__(*results)
        self.flushed = False
        self.fail_quote_insert = fail_quote_insert

    def begin_nested(self):
        return _Savepoint()

    async def flush(self):
        self.flushed = True

    async def execute(self, stmt):
        if self.fail_quote_insert and "INSERT INTO message_quotes" in str(stmt):
            raise RuntimeError("relation message_quotes does not exist")
        return await super().execute(stmt)


def _quoted_row(message_id, original=None):
    """The joined row load_quotes reads: (message id, original id, original sender, original body)."""
    if original is None:
        return (message_id, None, None, None)
    return (message_id, original.id, original.sender_id, original.body)


# ---- sending a reply ------------------------------------------------------------------------------

def test_a_reply_quotes_a_message_of_this_conversation(client):
    original = _msg(SAM, ME, "Dinner at 7?")
    mid = uuid.uuid4()
    db = _QuoteDb(
        _Result(None),                  # not already sent
        FRIEND,                         # we are friends
        _Result(rows=[(original.id,)]),  # the quoted message is in this conversation
        _Result(),                      # the quote row insert
        _Result(rows=[_quoted_row(mid, original)]),  # reading it back
    )
    _with_db(db)
    r = client.post(f"/messages/with/{SAM}", json={"id": str(mid), "body": "Yes!", "reply_to": str(original.id)})
    assert r.status_code == 200
    out = r.json()
    assert out["body"] == "Yes!"
    assert out["quote"] == {"id": str(original.id), "mine": False, "body": "Dinner at 7?", "deleted": False}
    assert db.flushed and db.committed


def test_a_message_that_is_not_in_this_conversation_cannot_be_quoted(client):
    db = _QuoteDb(_Result(None), FRIEND, _Result(rows=[]))
    _with_db(db)
    r = client.post(f"/messages/with/{SAM}", json={"id": str(uuid.uuid4()), "body": "hi", "reply_to": str(uuid.uuid4())})
    assert r.status_code == 404 and not db.added and not db.committed


def test_the_quote_lookup_is_limited_to_the_two_people_of_the_conversation():
    from sqlalchemy import select
    from sqlalchemy.dialects import postgresql

    from app.models.message import Message

    sql = str(select(Message.id).where(Message.id == uuid.uuid4(), router._pair(ME, SAM)).compile(dialect=postgresql.dialect()))
    assert "sender_id" in sql and "recipient_id" in sql


def test_without_the_quotes_table_the_message_is_still_sent_plain(client):
    original = _msg(SAM, ME, "hello")
    db = _QuoteDb(_Result(None), FRIEND, _Result(rows=[(original.id,)]), fail_quote_insert=True)
    _with_db(db)
    r = client.post(f"/messages/with/{SAM}", json={"id": str(uuid.uuid4()), "body": "hi", "reply_to": str(original.id)})
    assert r.status_code == 200 and r.json()["quote"] is None and db.committed


def test_a_plain_message_costs_no_extra_query(client):
    db = _QuoteDb(_Result(None), FRIEND)
    _with_db(db)
    assert client.post(f"/messages/with/{SAM}", json={"id": str(uuid.uuid4()), "body": "hey"}).status_code == 200
    assert len(db.statements) == 2 and not db.flushed


def test_retrying_a_reply_returns_it_with_its_quote(client):
    original = _msg(ME, SAM, "my own earlier line")
    mid = uuid.uuid4()
    db = _QuoteDb(_Result(_msg(ME, SAM, "reply", mid=mid)), _Result(rows=[_quoted_row(mid, original)]))
    _with_db(db)
    r = client.post(f"/messages/with/{SAM}", json={"id": str(mid), "body": "reply", "reply_to": str(original.id)})
    assert r.status_code == 200 and r.json()["quote"]["mine"] is True and not db.added


# ---- reading --------------------------------------------------------------------------------------------

def test_a_conversation_shows_each_reply_with_what_it_quotes(client):
    original = _msg(SAM, ME, "x" * 300)
    reply = _msg(ME, SAM, "that long one?", minutes=1)
    plain = _msg(SAM, ME, "plain", minutes=2)
    db = _QuoteDb(
        FRIEND,
        _Result(rows=[plain, reply, original]),   # newest first
        _Result(rows=[]),                          # no attachments
        _Result(rows=[_quoted_row(reply.id, original)]),
    )
    _with_db(db)
    out = client.get(f"/messages/with/{SAM}").json()["messages"]
    assert [m["body"][:4] for m in out] == ["xxxx", "that", "plai"]
    assert out[0]["quote"] is None and out[2]["quote"] is None
    quote = out[1]["quote"]
    assert quote["id"] == str(original.id) and quote["mine"] is False and not quote["deleted"]
    assert len(quote["body"]) <= router.QUOTE_CHARS and quote["body"].endswith("…")  # shortened


def test_a_quote_of_an_unsent_message_says_so_and_keeps_no_text(client):
    reply = _msg(ME, SAM, "replying", minutes=1)
    db = _QuoteDb(FRIEND, _Result(rows=[reply]), _Result(rows=[]), _Result(rows=[_quoted_row(reply.id, None)]))
    _with_db(db)
    quote = client.get(f"/messages/with/{SAM}").json()["messages"][0]["quote"]
    assert quote == {"id": None, "mine": None, "body": None, "deleted": True}


def test_a_thread_reads_all_its_quotes_in_one_query():
    class Counting(_QuoteDb):
        pass

    ids = [uuid.uuid4() for _ in range(40)]
    db = Counting(_Result(rows=[]))
    import asyncio

    asyncio.run(router.load_quotes(db, ids, ME))
    assert len(db.statements) == 1


def test_no_messages_no_query():
    import asyncio

    db = _QuoteDb()
    assert asyncio.run(router.load_quotes(db, [], ME)) == {}
    assert db.statements == []


def test_reading_quotes_never_breaks_the_conversation(client):
    reply = _msg(ME, SAM, "replying")
    # The plain fake db has no savepoint support, like a database without the table.
    db = _Db(FRIEND, _Result(rows=[reply]))
    _with_db(db)
    r = client.get(f"/messages/with/{SAM}")
    assert r.status_code == 200 and r.json()["messages"][0]["quote"] is None


@pytest.mark.parametrize("text, expected", [
    ("short", "short"),
    ("  lots   of\n space ", "lots of space"),
    ("y" * 500, "y" * (router.QUOTE_CHARS - 1) + "…"),
])
def test_a_quote_is_shortened_on_one_line(text, expected):
    assert router._shorten(text) == expected


def test_the_migration_keeps_no_copy_of_the_quoted_text():
    sql = open("migrations/2026-11-24_message_quotes.sql").read().lower()
    assert "on delete set null" in sql and "on delete cascade" in sql
    assert "enable row level security" in sql
    assert "body" not in sql.split("create table", 1)[1].split(");", 1)[0]  # the table has no text column
