"""Browser push notifications (Web Push)."""

import asyncio
import json
import uuid
from types import SimpleNamespace

import pytest
from pywebpush import WebPushException

from app.core.config import settings
from app.i18n import TABLES
from app.routers.notifications import TEST_BODY, TEST_TITLE
from app.services import push_sender

SUB = {"endpoint": "https://fcm.googleapis.com/fcm/send/abc123", "keys": {"p256dh": "BKey" * 20, "auth": "authsecret1234567"}}


def token(**over):
    return json.dumps({**SUB, **over})


@pytest.fixture
def web_on(monkeypatch):
    monkeypatch.setattr(settings, "push_mode", "web")
    monkeypatch.setattr(settings, "vapid_public_key", "PUBLICKEY")
    monkeypatch.setattr(settings, "vapid_private_key", "PRIVATEKEY")


class Pusher:
    """Stands in for pywebpush: records each send, answers per endpoint."""

    def __init__(self):
        self.calls, self.fail = [], {}

    async def __call__(self, **kw):
        self.calls.append(kw)
        status = self.fail.get(kw["subscription_info"]["endpoint"])
        if status is not None:
            raise WebPushException("refused", response=SimpleNamespace(status_code=status))
        return SimpleNamespace(status=201)


@pytest.fixture
def pusher(monkeypatch, web_on):
    p = Pusher()
    forgotten = []

    async def forget(tokens):
        forgotten.extend(tokens)

    monkeypatch.setattr(push_sender, "webpush_async", p)
    monkeypatch.setattr(push_sender, "_forget", forget)
    p.forgotten = forgotten
    return p


# ---- which subscriptions the server will talk to --------------------------------------------------------

@pytest.mark.parametrize("endpoint", [
    "https://fcm.googleapis.com/fcm/send/abc",
    "https://updates.push.services.mozilla.com/wpush/v2/abc",
    "https://web.push.apple.com/QabC",
    "https://wns2-par02p.notify.windows.com/w/?token=abc",
    "https://eu.push.services.mozilla.com/x",
])
def test_the_real_push_services_are_accepted(endpoint):
    assert push_sender.parse_subscription(token(endpoint=endpoint)) is not None


@pytest.mark.parametrize("endpoint", [
    "http://fcm.googleapis.com/fcm/send/abc",                 # not https
    "https://localhost/hook", "https://127.0.0.1/hook", "https://169.254.169.254/latest/meta-data",
    "https://10.0.0.5/x", "https://example.com/push",
    "https://fcm.googleapis.com.evil.example/x",              # a lookalike
    "https://evilfcm.googleapis.com/x", "https://notfcm.googleapis.com/x",
    "https://fcm.googleapis.com@evil.example/x",              # the real host is evil.example
    "https://user:pw@fcm.googleapis.com/x", "https://fcm.googleapis.com:8443/x",
    "https://evil.example/.push.apple.com", "ftp://fcm.googleapis.com/x", "", None, 5, "https://" + "a" * 3000,
])
def test_anything_else_is_refused_so_the_server_cannot_be_aimed_at_other_addresses(endpoint):
    assert push_sender.parse_subscription(token(endpoint=endpoint)) is None


@pytest.mark.parametrize("raw", [
    "x" * 64, "not json {", "[]", "{}", token(keys={}), token(keys={"p256dh": "a"}), token(keys={"p256dh": "", "auth": "b"}),
    token(keys="nope"), token(keys={"p256dh": 1, "auth": 2}),
])
def test_phone_tokens_and_broken_subscriptions_are_not_browser_subscriptions(raw):
    assert push_sender.parse_subscription(raw) is None


def test_only_the_needed_fields_are_kept():
    parsed = push_sender.parse_subscription(token(extra="x", expirationTime=None))
    assert set(parsed) == {"endpoint", "keys"} and set(parsed["keys"]) == {"p256dh", "auth"}


# ---- sending ----------------------------------------------------------------------------------------------------

def test_dry_run_still_sends_nothing(monkeypatch, pusher):
    monkeypatch.setattr(settings, "push_mode", "dry_run")
    assert asyncio.run(push_sender.send([token()], "a", "b")) == "dry_run" and pusher.calls == []


def test_web_mode_without_keys_says_so_instead_of_pretending(monkeypatch, web_on):
    monkeypatch.setattr(settings, "vapid_private_key", "")
    assert not push_sender.web_push_ready()
    with pytest.raises(push_sender.PushUnavailable):
        asyncio.run(push_sender.send([token()], "a", "b"))


def test_a_push_carries_the_words_and_is_signed_with_a_web_address_not_an_email(pusher):
    status = asyncio.run(push_sender.send([token()], "🔥 Hi", "Sam sent you a bite", {"kind": "friend_snap"}))
    assert status == "sent"
    call = pusher.calls[0]
    assert json.loads(call["data"]) == {"title": "🔥 Hi", "body": "Sam sent you a bite", "data": {"kind": "friend_snap"}}
    assert call["vapid_private_key"] == "PRIVATEKEY"
    sub = call["vapid_claims"]["sub"]
    assert sub.startswith("https://") and "@" not in sub
    assert call["ttl"] == push_sender.TTL_SECONDS and call["subscription_info"]["endpoint"] == SUB["endpoint"]


def test_a_browser_that_unsubscribed_is_forgotten_and_the_others_still_get_it(pusher):
    gone, fine = token(endpoint="https://fcm.googleapis.com/fcm/send/gone"), token(endpoint="https://web.push.apple.com/fine")
    pusher.fail["https://fcm.googleapis.com/fcm/send/gone"] = 410
    assert asyncio.run(push_sender.send([gone, fine], "a", "b")) == "sent"
    assert pusher.forgotten == [gone]


def test_when_every_send_fails_it_is_recorded_as_failed_and_only_dead_ones_are_forgotten(pusher):
    a, b = token(endpoint="https://fcm.googleapis.com/fcm/send/a"), token(endpoint="https://fcm.googleapis.com/fcm/send/b")
    pusher.fail.update({"https://fcm.googleapis.com/fcm/send/a": 404, "https://fcm.googleapis.com/fcm/send/b": 500})
    assert asyncio.run(push_sender.send([a, b], "a", "b")) == "failed"
    assert pusher.forgotten == [a]  # a 500 is the service having a bad moment, not an unsubscribe


def test_a_transport_error_is_a_failure_not_a_crash(monkeypatch, pusher):
    async def boom(**kw):
        raise ConnectionError("https://fcm.googleapis.com/secret-endpoint")

    monkeypatch.setattr(push_sender, "webpush_async", boom)
    assert asyncio.run(push_sender.send([token()], "a", "b")) == "failed"


def test_only_browser_tokens_are_used_and_without_any_there_is_nobody_to_tell(pusher):
    assert asyncio.run(push_sender.send(["x" * 64], "a", "b")) == "no_device"
    assert asyncio.run(push_sender.send(["x" * 64, token()], "a", "b")) == "sent" and len(pusher.calls) == 1


def test_one_person_cannot_make_the_server_send_to_a_crowd(pusher):
    tokens = [token(endpoint=f"https://fcm.googleapis.com/fcm/send/{n}") for n in range(40)]
    asyncio.run(push_sender.send(tokens, "a", "b"))
    assert len(pusher.calls) == push_sender.MAX_DEVICES_PER_SEND


def test_the_real_library_signs_and_encrypts_with_a_real_key_pair(monkeypatch, web_on):
    """No mock: the keys the script makes must be accepted by pywebpush, and a
    browser-sized subscription must encrypt. The request itself is intercepted."""
    import base64
    import subprocess
    import sys

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    out = subprocess.run([sys.executable, "scripts/generate_vapid_keys.py"], capture_output=True, text=True, check=True).stdout
    keys = dict(line.split("=", 1) for line in out.strip().splitlines())
    assert len(base64.urlsafe_b64decode(keys["VAPID_PUBLIC_KEY"] + "==")) == 65  # an uncompressed P-256 point
    monkeypatch.setattr(settings, "vapid_private_key", keys["VAPID_PRIVATE_KEY"])

    browser = ec.generate_private_key(ec.SECP256R1())
    p256dh = base64.urlsafe_b64encode(
        browser.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    ).rstrip(b"=").decode()
    auth = base64.urlsafe_b64encode(b"0123456789abcdef").rstrip(b"=").decode()
    sub = {"endpoint": "https://fcm.googleapis.com/fcm/send/real", "keys": {"p256dh": p256dh, "auth": auth}}

    seen = {}

    class FakeSession:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, endpoint, **params):
            seen.update(endpoint=endpoint, headers=params["headers"], body=params["data"])

            class R:
                status = 201

                async def text(self):
                    return ""

            return R()

    import aiohttp

    monkeypatch.setattr(aiohttp, "ClientSession", FakeSession)
    assert asyncio.run(push_sender.send([json.dumps(sub)], "Title", "Body 🔥")) == "sent"
    assert seen["endpoint"] == sub["endpoint"]
    assert seen["headers"]["Authorization"].startswith("vapid ")
    assert seen["headers"]["Content-Encoding"] == "aes128gcm" and seen["body"]


# ---- the routes ---------------------------------------------------------------------------------------------------

class _Result:
    def __init__(self, rows=None):
        self.rows = rows or []

    def scalars(self):
        return SimpleNamespace(all=lambda: self.rows)


class _Db:
    def __init__(self, *results):
        self.results, self.executed, self.committed = list(results), [], False

    async def execute(self, stmt):
        self.executed.append(stmt)
        return self.results.pop(0) if self.results else _Result()

    async def commit(self):
        self.committed = True


def _with_db(db):
    from app.core.database import get_db
    from app.main import app

    async def fake_db():
        yield db

    app.dependency_overrides[get_db] = fake_db


def test_a_browser_can_register_and_a_broken_subscription_cannot(client):
    db = _Db()
    _with_db(db)
    ok = client.post("/notifications/devices", json={"token": token(), "platform": "web", "utc_offset_minutes": 60})
    assert ok.status_code == 204 and db.committed
    for bad in [
        {"token": "x" * 64, "platform": "web"},
        {"token": token(endpoint="https://example.com/push"), "platform": "web"},
        {"token": token(endpoint="https://169.254.169.254/latest"), "platform": "web"},
    ]:
        assert client.post("/notifications/devices", json=bad).status_code == 422
    assert client.post("/notifications/devices", json={"token": "x" * 64, "platform": "ios"}).status_code == 204


def test_a_subscription_is_removed_by_body_and_only_your_own(client):
    db = _Db()
    _with_db(db)
    assert client.post("/notifications/devices/remove", json={"token": token()}).status_code == 204
    assert "user_id" in str(db.executed[0].compile()) and db.committed
    assert client.post("/notifications/devices/remove", json={"token": "short"}).status_code == 422


def test_the_app_learns_whether_browsers_can_be_notified_and_the_public_key(client, monkeypatch):
    monkeypatch.setattr(settings, "push_mode", "dry_run")
    assert client.get("/notifications/web-push").json() == {"enabled": False, "public_key": None}
    monkeypatch.setattr(settings, "push_mode", "web")
    monkeypatch.setattr(settings, "vapid_public_key", "PUB")
    monkeypatch.setattr(settings, "vapid_private_key", "")
    assert client.get("/notifications/web-push").json()["enabled"] is False  # half set up is off
    monkeypatch.setattr(settings, "vapid_private_key", "PRIV")
    body = client.get("/notifications/web-push").json()
    assert body == {"enabled": True, "public_key": "PUB"} and "PRIV" not in json.dumps(body)


def test_the_web_push_routes_need_a_login(anon_client):
    assert anon_client.get("/notifications/web-push").status_code in (401, 403)
    assert anon_client.post("/notifications/test").status_code in (401, 403)
    assert anon_client.post("/notifications/devices/remove", json={"token": "x" * 20}).status_code in (401, 403, 422)


@pytest.fixture(autouse=True)
def _fresh_limit():
    from app.core.rate_limit import push_tests

    push_tests.reset()
    yield
    push_tests.reset()


def test_a_test_notification_goes_to_your_devices_in_your_language(client, pusher):
    _with_db(_Db(_Result([token()])))
    assert client.post("/notifications/test", headers={"Accept-Language": "es"}).json() == {"status": "sent"}
    sent = json.loads(pusher.calls[0]["data"])
    assert sent["title"] == TABLES["es"][TEST_TITLE] and sent["body"] == TABLES["es"][TEST_BODY]
    assert sent["data"] == {"kind": "test"}


def test_a_test_with_no_device_says_so_and_every_language_has_the_words(client, pusher):
    _with_db(_Db(_Result([])))
    assert client.post("/notifications/test").json() == {"status": "no_device"} and pusher.calls == []
    for code, table in TABLES.items():
        assert table[TEST_TITLE] != TEST_TITLE and table[TEST_BODY] != TEST_BODY, code


def test_in_dry_run_the_test_says_so(client, monkeypatch):
    monkeypatch.setattr(settings, "push_mode", "dry_run")
    _with_db(_Db(_Result([token()])))
    assert client.post("/notifications/test").json() == {"status": "dry_run"}


def test_tests_are_limited(client, pusher):
    _with_db(_Db(*[_Result([token()]) for _ in range(8)]))
    codes = [client.post("/notifications/test").status_code for _ in range(7)]
    assert codes[:5] == [200] * 5 and codes[5:] == [429, 429]


async def test_a_real_notification_reaches_a_browser_through_the_notifier(pusher):
    from datetime import datetime, timezone

    from app.services import notifier
    from app.services.notification_rules import Kind

    class R:
        def __init__(self, rows=None, one=None, scalar=0):
            self.rows, self.one, self.scalar = rows or [], one, scalar

        def scalars(self):
            return self

        def all(self):
            return self.rows

        def scalar_one_or_none(self):
            return self.one

        def scalar_one(self):
            return self.scalar

    class Sp:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    class Db:
        def begin_nested(self):
            return Sp()

        async def execute(self, stmt):
            text = str(stmt)
            if "device_tokens" in text and text.lstrip().upper().startswith("SELECT"):
                return R(rows=[token()])
            if "user_language" in text:
                return R(one="fr")
            if "count(" in text:
                return R(scalar=0)
            if text.lstrip().upper().startswith("INSERT"):
                return R(one=uuid.uuid4())
            return R()

        async def commit(self):
            pass

    status = await notifier.notify(
        Db(), uuid.uuid4(), Kind.FRIEND_SNAP, dedupe_key="snap:1", name="sam",
        now=datetime(2026, 11, 20, 13, 0, tzinfo=timezone.utc),
    )
    assert status == "sent"
    sent = json.loads(pusher.calls[0]["data"])
    assert "sam" in sent["title"] and sent["data"] == {"kind": "friend_snap"}
