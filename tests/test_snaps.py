import base64
import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services.pair_streak import pair_streak

ME = uuid.UUID("00000000-0000-0000-0000-000000000001")
SAM = uuid.UUID("00000000-0000-0000-0000-000000000002")
TODAY = date(2026, 11, 5)


def d(n):  # n days ago
    return TODAY - timedelta(days=n)


# --- pair streak rules -----------------------------------------------------

def test_no_history_is_zero():
    s = pair_streak(set(), set(), TODAY)
    assert (s.count, s.sent_today, s.they_sent_today, s.at_risk) == (0, False, False, False)


def test_both_sending_every_day_builds_the_streak():
    both = {d(0), d(1), d(2), d(3)}
    s = pair_streak(both, both, TODAY)
    assert s.count == 4 and s.complete_today and not s.at_risk


def test_one_sided_days_do_not_count():
    # I sent three days running, they only sent yesterday: only yesterday is mutual.
    assert pair_streak({d(0), d(1), d(2)}, {d(1)}, TODAY).count == 1
    # Nothing they sent lines up with anything I sent.
    assert pair_streak({d(0), d(2)}, {d(1), d(3)}, TODAY).count == 0


def test_today_unfinished_keeps_yesterdays_run_alive_but_at_risk():
    s = pair_streak({d(1), d(2), d(0)}, {d(1), d(2)}, TODAY)
    assert s.count == 2 and s.sent_today and not s.they_sent_today
    assert s.at_risk and not s.complete_today


def test_a_missed_day_resets_to_zero():
    both = {d(2), d(3), d(4)}  # nothing yesterday or today
    assert pair_streak(both, both, TODAY).count == 0


def test_a_gap_ends_the_run():
    both = {d(0), d(1), d(3), d(4), d(5)}
    assert pair_streak(both, both, TODAY).count == 2


def test_completing_today_extends_yesterdays_streak():
    s = pair_streak({d(0), d(1), d(2)}, {d(0), d(1), d(2)}, TODAY)
    assert s.count == 3 and s.complete_today


# --- request handling ------------------------------------------------------

@pytest.fixture
def storage(monkeypatch):
    from app.core.config import settings
    from app.services import storage_service

    monkeypatch.setattr(settings, "supabase_service_role_key", "service-key")
    calls = {"uploads": [], "deleted": []}

    async def upload(path, data, mime):
        calls["uploads"].append((path, mime, len(data)))

    async def delete(paths):
        calls["deleted"].extend(paths)

    monkeypatch.setattr(storage_service, "upload", upload)
    monkeypatch.setattr(storage_service, "delete", delete)
    return calls


class _Result:
    def __init__(self, value=None, rows=None):
        self.value, self.rows = value, rows or []

    def scalar_one_or_none(self):
        return self.value

    def scalars(self):
        return SimpleNamespace(all=lambda: self.rows)

    def all(self):
        return self.rows


class _Db:
    def __init__(self, *results):
        self.results = list(results)
        self.added, self.committed, self.rolled_back = [], False, False

    async def execute(self, stmt):
        return self.results.pop(0)

    def add(self, obj):
        self.added.append(obj)

    def add_all(self, objs):
        self.added.extend(objs)

    async def flush(self):
        pass

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


JPEG = base64.b64encode(b"\xff\xd8\xff" + b"x" * 100).decode()


def body(**kw):
    base = dict(id=str(uuid.uuid4()), image=JPEG, recipient_ids=[str(SAM)])
    base.update(kw)
    return base


def test_sending_needs_storage_to_be_configured(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "supabase_service_role_key", None)
    _with_db(_Db())
    r = client.post("/snaps", json=body())
    assert r.status_code == 503


def test_cannot_send_to_yourself(client, storage):
    _with_db(_Db())
    assert client.post("/snaps", json=body(recipient_ids=[str(ME)])).status_code == 422


def test_validation_errors(client, storage):
    _with_db(_Db(_Result(None)))
    assert client.post("/snaps", json=body(image="!!!not base64!!!")).status_code == 400
    _with_db(_Db(_Result(None)))
    assert client.post("/snaps", json=body(image=base64.b64encode(b"GIF89a" + b"x" * 50).decode())).status_code == 415
    _with_db(_Db(_Result(None)))
    big = base64.b64encode(b"\xff\xd8\xff" + b"x" * (2 * 1024 * 1024 + 10)).decode()
    assert client.post("/snaps", json=body(image=big)).status_code == 413
    assert client.post("/snaps", json=body(recipient_ids=[])).status_code == 422
    assert client.post("/snaps", json=body(caption="x" * 121)).status_code == 422
    assert not storage["uploads"]


def test_only_friends_can_receive(client, storage):
    _with_db(_Db(_Result(None), _Result(rows=[])))  # no existing snap; no friends
    r = client.post("/snaps", json=body())
    assert r.status_code == 403 and not storage["uploads"]


def test_a_good_snap_is_uploaded_saved_and_reports_the_streak(client, storage):
    today = datetime.now(timezone.utc).date()
    db = _Db(
        _Result(None),                       # no existing snap
        _Result(rows=[(ME, SAM)]),           # friendship rows
        _Result(),                           # snap_days insert
        _Result(rows=[(SAM, "Sam")]),        # usernames
        _Result(rows=[(ME, SAM, today), (SAM, ME, today)]),  # they already sent today
        _Result(rows=[(ME, "Me")]),         # the sender's name, for the notification
    )
    _with_db(db)
    r = client.post("/snaps", json=body(caption=" yum "))
    assert r.status_code == 200
    out = r.json()
    assert out["recipients"] == [{"user_id": str(SAM), "username": "Sam", "streak": 1, "completed_today": True}]
    assert storage["uploads"][0][1] == "image/jpeg"
    assert storage["uploads"][0][0].startswith(f"{ME}/")
    assert db.committed
    assert db.added[0].caption == "yum"


def test_a_failed_save_removes_the_uploaded_photo(client, storage):
    class Boom(_Db):
        async def commit(self):
            raise RuntimeError("db down")

    _with_db(Boom(_Result(None), _Result(rows=[(ME, SAM)]), _Result()))
    r = client.post("/snaps", json=body())
    assert r.status_code == 500
    assert storage["deleted"] == [storage["uploads"][0][0]]


def test_resending_the_same_id_is_a_no_op(client, storage):
    existing = SimpleNamespace(id=uuid.uuid4(), sender_id=ME, expires_at=datetime.now(timezone.utc))
    db = _Db(_Result(existing), _Result(rows=[SAM]), _Result(rows=[(SAM, "Sam")]), _Result(rows=[]))
    _with_db(db)
    r = client.post("/snaps", json=body(id=str(existing.id)))
    assert r.status_code == 200 and not storage["uploads"] and not db.committed


def test_someone_elses_snap_id_is_refused(client, storage):
    existing = SimpleNamespace(id=uuid.uuid4(), sender_id=SAM, expires_at=datetime.now(timezone.utc))
    _with_db(_Db(_Result(existing)))
    assert client.post("/snaps", json=body(id=str(existing.id))).status_code == 409


def test_reactions_are_a_fixed_set(client):
    _with_db(_Db())
    sid = uuid.uuid4()
    assert client.post(f"/snaps/{sid}/react", json={"emoji": "💩"}).status_code == 422
    _with_db(_Db(_Result(None)))  # not a recipient / expired
    assert client.post(f"/snaps/{sid}/react", json={"emoji": "🔥"}).status_code == 404


def test_view_and_report_need_a_live_snap_addressed_to_you(client):
    sid = uuid.uuid4()
    _with_db(_Db(_Result(None)))
    assert client.post(f"/snaps/{sid}/view").status_code == 404
    _with_db(_Db(_Result(None)))
    assert client.post(f"/snaps/{sid}/report", json={"reason": "rude"}).status_code == 404


def test_report_is_recorded_against_the_sender(client):
    db = _Db(_Result(SAM))
    _with_db(db)
    r = client.post(f"/snaps/{uuid.uuid4()}/report", json={"reason": " not food "})
    assert r.status_code == 204 and db.committed
    rep = db.added[0]
    assert rep.reporter_id == ME and rep.reported_user_id == SAM and rep.reason == "not food"


def test_purge_is_off_without_a_secret_and_guarded_with_one(client, monkeypatch, storage):
    from app.core.config import settings
    from app.routers import snaps

    async def fake_purge(limit=100):
        return 3

    monkeypatch.setattr(snaps, "purge_expired", fake_purge)
    monkeypatch.setattr(settings, "cron_secret", None)
    assert client.post("/snaps/purge").status_code == 404

    monkeypatch.setattr(settings, "cron_secret", "s3cret")
    assert client.post("/snaps/purge").status_code == 403
    assert client.post("/snaps/purge", headers={"X-Cron-Secret": "wrong"}).status_code == 403
    r = client.post("/snaps/purge", headers={"X-Cron-Secret": "s3cret"})
    assert r.status_code == 200 and r.json() == {"purged": 3}


def test_the_friends_list_carries_pair_streaks(client):
    from app.core.dates import resolve_today

    today = resolve_today(None)
    t = datetime(2026, 11, 4, tzinfo=timezone.utc)
    row = SimpleNamespace(id=uuid.uuid4(), requester_id=ME, addressee_id=SAM, status="accepted",
                          created_at=t, responded_at=t)
    db = _Db(
        _Result(rows=[row]),
        _Result(rows=[(SAM, "Sam")]),
        _Result(rows=[(ME, SAM, today), (SAM, ME, today), (ME, SAM, today - timedelta(days=1)),
                      (SAM, ME, today - timedelta(days=1))]),
    )
    # list_friends reads scalars().all() for the first query
    _with_db(db)
    r = client.get("/friends", params={"date": today.isoformat()})
    assert r.status_code == 200
    f = r.json()["friends"][0]
    assert (f["streak"], f["sent_today"], f["they_sent_today"]) == (2, True, True)


def test_the_friends_list_still_loads_if_the_snaps_tables_are_missing(client):
    from app.core.dates import resolve_today

    class NoTable(_Db):
        async def execute(self, stmt):
            if not self.results:
                raise RuntimeError('relation "snap_days" does not exist')
            return self.results.pop(0)

    t = datetime(2026, 11, 4, tzinfo=timezone.utc)
    row = SimpleNamespace(id=uuid.uuid4(), requester_id=ME, addressee_id=SAM, status="accepted",
                          created_at=t, responded_at=t)
    _with_db(NoTable(_Result(rows=[row]), _Result(rows=[(SAM, "Sam")])))
    r = client.get("/friends", params={"date": resolve_today(None).isoformat()})
    assert r.status_code == 200
    assert r.json()["friends"][0]["streak"] is None
