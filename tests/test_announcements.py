"""One-off "what's new" push to everyone: who gets it, never twice, safe to preview."""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.i18n import TABLES
from app.services import announcements, notifier, push_sender
from app.services.notification_rules import ANNOUNCEMENTS, Kind, Prefs, copy_for, decide

RELEASE = "nov-21-2026-bites-home"
NOW = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)
A, B, C = (uuid.UUID(f"00000000-0000-0000-0000-0000000000{n:02d}") for n in (11, 12, 13))


# --- the words ---------------------------------------------------------------

def test_every_announcement_is_translated_everywhere():
    for title, body in ANNOUNCEMENTS.values():
        for lang, table in TABLES.items():
            assert title in table and body in table, f"{lang}: {title}"


def test_copy_is_in_the_persons_language_and_is_short_and_kind():
    for lang in ("en", "es", "fr", "de", "pt", "it"):
        title, body = copy_for(Kind.ANNOUNCEMENT, "k", lang, release=RELEASE)
        assert title and body
        assert len(title) <= 60 and len(body) <= 100, "a push is read on a lock screen"
    es_title, _ = copy_for(Kind.ANNOUNCEMENT, "k", "es", release=RELEASE)
    assert es_title != ANNOUNCEMENTS[RELEASE][0]
    text = " ".join(ANNOUNCEMENTS[RELEASE]).lower()
    for banned in ("cheat", "guilt", "burn off", "miss you", "calorie", "weight"):
        assert banned not in text


# --- the rules still apply ---------------------------------------------------

def test_an_announcement_respects_pause_quiet_hours_and_the_cap():
    night = datetime(2026, 11, 21, 23, 0, tzinfo=timezone.utc)
    assert decide(Kind.ANNOUNCEMENT, Prefs(), night, 0).reason == "quiet_hours"
    assert decide(Kind.ANNOUNCEMENT, Prefs(paused_until=datetime(2026, 12, 1, tzinfo=timezone.utc)), NOW, 0).reason == "paused"
    assert decide(Kind.ANNOUNCEMENT, Prefs(), NOW, 3).reason == "daily_cap"
    assert decide(Kind.ANNOUNCEMENT, Prefs(), NOW, 0).allowed


def test_switching_every_kind_off_does_not_hide_it_but_pause_does():
    all_off = Prefs(friend_snaps=False, reactions=False, streak_reminders=False, milestones=False)
    assert decide(Kind.ANNOUNCEMENT, all_off, NOW, 0).allowed


# --- the broadcast -----------------------------------------------------------

class _Scalars:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return list(self.rows)


class _Result:
    def __init__(self, rows=()):
        self.rows = rows

    def scalars(self):
        return _Scalars(self.rows)


class _Db:
    """First execute() returns the people; later ones (cleanup deletes) are recorded."""

    def __init__(self, people):
        self.people = people
        self.statements = []
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, stmt):
        self.statements.append(stmt)
        return _Result(self.people if len(self.statements) == 1 else ())

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


@pytest.fixture
def fake_notifier(monkeypatch):
    calls = SimpleNamespace(notify=[], preview=[], answers={})

    async def notify(db, uid, kind, *, dedupe_key=None, now=None, **ctx):
        calls.notify.append((uid, kind, dedupe_key, ctx))
        answer = calls.answers.get(uid, "sent")
        if isinstance(answer, Exception):
            raise answer
        return answer

    async def preview(db, uid, kind, *, dedupe_key=None, now=None):
        calls.preview.append((uid, kind, dedupe_key))
        return calls.answers.get(uid, "would_send")

    monkeypatch.setattr(notifier, "notify", notify)
    monkeypatch.setattr(notifier, "preview", preview)
    return calls


async def test_preview_counts_and_sends_nothing(fake_notifier):
    fake_notifier.answers = {B: "quiet_hours", C: "duplicate"}
    out = await announcements.broadcast(_Db([A, B, C]), RELEASE, send=False, now=NOW)
    assert out == {"mode": "preview", "people": 3, "counts": {"would_send": 1, "quiet_hours": 1, "duplicate": 1}, "more": False}
    assert fake_notifier.notify == []
    assert len(fake_notifier.preview) == 3


async def test_send_notifies_everyone_once_with_a_stable_key(fake_notifier):
    out = await announcements.broadcast(_Db([A, B]), RELEASE, send=True, now=NOW)
    assert out["mode"] == "send" and out["counts"] == {"sent": 2} and out["more"] is False
    assert [c[0] for c in fake_notifier.notify] == [A, B]
    assert {c[2] for c in fake_notifier.notify} == {f"announce:{RELEASE}"}
    assert all(c[1] is Kind.ANNOUNCEMENT and c[3] == {"release": RELEASE} for c in fake_notifier.notify)


async def test_a_second_run_reaches_nobody_again(fake_notifier):
    fake_notifier.answers = {A: "duplicate", B: "duplicate"}
    out = await announcements.broadcast(_Db([A, B]), RELEASE, send=True, now=NOW)
    assert out["counts"] == {"duplicate": 2}


async def test_the_limit_stops_and_says_there_is_more(fake_notifier):
    out = await announcements.broadcast(_Db([A, B, C]), RELEASE, send=True, limit=2, now=NOW)
    assert out["counts"] == {"sent": 2} and out["more"] is True
    assert [c[0] for c in fake_notifier.notify] == [A, B]


async def test_people_who_were_skipped_do_not_use_up_the_limit(fake_notifier):
    fake_notifier.answers = {A: "duplicate", B: "quiet_hours"}
    out = await announcements.broadcast(_Db([A, B, C]), RELEASE, send=True, limit=1, now=NOW)
    assert out["counts"] == {"duplicate": 1, "quiet_hours": 1, "sent": 1} and out["more"] is False


async def test_a_failed_delivery_frees_the_claim_so_a_rerun_retries(fake_notifier):
    fake_notifier.answers = {A: "failed"}
    db = _Db([A])
    out = await announcements.broadcast(db, RELEASE, send=True, now=NOW)
    assert out["counts"] == {"failed": 1}
    assert db.commits == 1 and len(db.statements) == 2, "one delete of the failed claim, then committed"
    assert "DELETE" in str(db.statements[1]).upper()


async def test_one_persons_error_does_not_stop_the_others(fake_notifier):
    fake_notifier.answers = {A: RuntimeError("db hiccup")}
    db = _Db([A, B])
    out = await announcements.broadcast(db, RELEASE, send=True, now=NOW)
    assert out["counts"] == {"error": 1, "sent": 1}
    assert db.rollbacks == 1


async def test_an_unknown_release_is_refused(fake_notifier):
    with pytest.raises(KeyError):
        await announcements.broadcast(_Db([A]), "nope", send=True, now=NOW)
    assert fake_notifier.notify == []


# --- the real preview against the rules --------------------------------------

class _One:
    def __init__(self, value=None, first=None, rows=()):
        self.value, self._first, self.rows = value, first, rows

    def scalars(self):
        return _Scalars(self.rows)

    def scalar_one_or_none(self):
        return self.value

    def scalar_one(self):
        return self.value

    def first(self):
        return self._first


class _Script:
    def __init__(self, *results):
        self.results = list(results)

    async def execute(self, stmt):
        return self.results.pop(0)


async def test_preview_without_a_device_says_so():
    assert await notifier.preview(_Script(_One(rows=[])), A, Kind.ANNOUNCEMENT, now=NOW) == "no_device"


async def test_preview_says_would_send_when_the_rules_allow():
    db = _Script(_One(rows=["tok"]), _One(value=None), _One(value=0), _One(first=None))
    assert await notifier.preview(db, A, Kind.ANNOUNCEMENT, dedupe_key="k", now=NOW) == "would_send"


async def test_preview_sees_someone_already_told():
    db = _Script(_One(rows=["tok"]), _One(value=None), _One(value=0), _One(first=("id",)))
    assert await notifier.preview(db, A, Kind.ANNOUNCEMENT, dedupe_key="k", now=NOW) == "duplicate"


async def test_preview_respects_the_daily_cap():
    db = _Script(_One(rows=["tok"]), _One(value=None), _One(value=3))
    assert await notifier.preview(db, A, Kind.ANNOUNCEMENT, dedupe_key="k", now=NOW) == "daily_cap"


# --- the endpoint ------------------------------------------------------------

def _with_db(db):
    from app.core.database import get_db
    from app.main import app

    async def fake_db():
        yield db

    app.dependency_overrides[get_db] = fake_db


URL = "/notifications/cron/announce"
HEAD = {"X-Cron-Secret": "s3cret"}


def test_the_endpoint_is_off_without_a_secret_and_guarded_with_one(client, monkeypatch):
    monkeypatch.setattr(settings, "cron_secret", None)
    assert client.post(URL, json={"release": RELEASE}).status_code == 404
    monkeypatch.setattr(settings, "cron_secret", "s3cret")
    assert client.post(URL, json={"release": RELEASE}).status_code == 403
    assert client.post(URL, json={"release": RELEASE}, headers={"X-Cron-Secret": "nope"}).status_code == 403


def test_an_unknown_release_is_a_404(client, monkeypatch):
    monkeypatch.setattr(settings, "cron_secret", "s3cret")
    assert client.post(URL, json={"release": "nope"}, headers=HEAD).status_code == 404


def test_it_previews_by_default_and_sends_nothing(client, monkeypatch, fake_notifier):
    monkeypatch.setattr(settings, "cron_secret", "s3cret")
    _with_db(_Db([A, B]))
    r = client.post(URL, json={"release": RELEASE}, headers=HEAD)
    assert r.status_code == 200
    assert r.json() == {"mode": "preview", "people": 2, "counts": {"would_send": 2}, "more": False}
    assert fake_notifier.notify == []


def test_sending_is_refused_while_push_is_only_a_dry_run(client, monkeypatch, fake_notifier):
    monkeypatch.setattr(settings, "cron_secret", "s3cret")
    monkeypatch.setattr(settings, "push_mode", "dry_run")
    _with_db(_Db([A]))
    r = client.post(URL, json={"release": RELEASE, "send": True}, headers=HEAD)
    assert r.status_code == 409
    assert fake_notifier.notify == [], "a dry run must never claim the once-only key"


def test_sending_works_when_web_push_is_ready(client, monkeypatch, fake_notifier):
    monkeypatch.setattr(settings, "cron_secret", "s3cret")
    monkeypatch.setattr(push_sender, "web_push_ready", lambda: True)
    _with_db(_Db([A, B]))
    r = client.post(URL, json={"release": RELEASE, "send": True, "limit": 1}, headers=HEAD)
    assert r.status_code == 200
    assert r.json() == {"mode": "send", "people": 2, "counts": {"sent": 1}, "more": True}


def test_the_limit_is_bounded(client, monkeypatch):
    monkeypatch.setattr(settings, "cron_secret", "s3cret")
    assert client.post(URL, json={"release": RELEASE, "limit": 0}, headers=HEAD).status_code == 422
    assert client.post(URL, json={"release": RELEASE, "limit": 100000}, headers=HEAD).status_code == 422
