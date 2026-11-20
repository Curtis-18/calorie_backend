"""Delivering a push.

Two modes. "dry_run" (the default) reports what it would have done and sends
nothing, so the whole pipeline (caps, quiet hours, the log) runs and is
testable without any credentials. "web" sends to browsers through the Web Push
protocol, signed with the VAPID keys in the settings. Phones (APNs/FCM) need the
Apple Developer account and Firebase and have no provider yet.

A web "token" is the browser's push subscription as JSON text
(`{"endpoint": ..., "keys": {"p256dh": ..., "auth": ...}}`). Because the
server will POST to the endpoint a person's browser gave it, only the push
services browsers really use are accepted (otherwise a signed-in person could
make the server call any address).
"""

import asyncio
import json
import logging
from urllib.parse import urlsplit

from pywebpush import WebPushException, webpush_async
from sqlalchemy import delete

from app.core import database
from app.core.config import settings
from app.models.notification import DeviceToken

log = logging.getLogger("calorie_backend")

# The push services behind Chrome/Edge/Android, Firefox, Safari/iOS and Windows.
_ALLOWED_HOSTS = ("fcm.googleapis.com",)
_ALLOWED_SUFFIXES = (".push.services.mozilla.com", ".push.apple.com", ".notify.windows.com")
_ALLOWED_EXACT = ("push.services.mozilla.com", "updates.push.services.mozilla.com", "web.push.apple.com")

TTL_SECONDS = 3600  # an hour-old reminder is no longer useful
SEND_TIMEOUT = 10
MAX_DEVICES_PER_SEND = 10


class PushUnavailable(Exception):
    """The configured provider could not deliver."""


def web_push_ready() -> bool:
    return settings.push_mode == "web" and bool(settings.vapid_public_key and settings.vapid_private_key)


def _allowed_endpoint(endpoint: object) -> bool:
    if not isinstance(endpoint, str) or len(endpoint) > 2048:
        return False
    try:
        parts = urlsplit(endpoint)
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError:
        return False
    if parts.scheme != "https" or parts.username or parts.password or port not in (None, 443):
        return False
    return host in _ALLOWED_HOSTS or host in _ALLOWED_EXACT or host.endswith(_ALLOWED_SUFFIXES)


def parse_subscription(token: str) -> dict | None:
    """The browser subscription inside [token], or None when it is not one
    (a phone token) or is not safe to send to."""
    if not token.startswith("{"):
        return None
    try:
        sub = json.loads(token)
    except ValueError:
        return None
    if not isinstance(sub, dict) or not _allowed_endpoint(sub.get("endpoint")):
        return None
    keys = sub.get("keys")
    if not isinstance(keys, dict) or not all(isinstance(keys.get(k), str) and keys.get(k) for k in ("p256dh", "auth")):
        return None
    return {"endpoint": sub["endpoint"], "keys": {"p256dh": keys["p256dh"], "auth": keys["auth"]}}


async def _forget(tokens: list[str]) -> None:
    """Drop subscriptions the push service says no longer exist. Best effort."""
    try:
        async with database.async_session_maker() as session:
            await session.execute(delete(DeviceToken).where(DeviceToken.token.in_(tokens)))
            await session.commit()
    except Exception:  # noqa: BLE001
        log.warning("could not remove dead push subscriptions", exc_info=True)


async def _send_one(token: str, sub: dict, payload: str) -> str:
    """"ok", "gone" (the browser unsubscribed or the subscription expired) or "failed"."""
    try:
        await webpush_async(
            subscription_info=sub,
            data=payload,
            vapid_private_key=settings.vapid_private_key,
            vapid_claims={"sub": settings.vapid_subject},
            ttl=TTL_SECONDS,
            timeout=SEND_TIMEOUT,
        )
        return "ok"
    except WebPushException as exc:
        if exc.status_code in (404, 410):
            return "gone"
        # The status only: the message can carry the endpoint address.
        log.warning("web push refused, status=%s", exc.status_code)
        return "failed"
    except Exception as exc:  # noqa: BLE001
        log.warning("web push failed: %s", type(exc).__name__)
        return "failed"


async def _send_web(tokens: list[str], title: str, body: str, data: dict[str, str] | None) -> str:
    subs = [(t, s) for t in tokens if (s := parse_subscription(t)) is not None][:MAX_DEVICES_PER_SEND]
    if not subs:
        return "no_device"
    payload = json.dumps({"title": title, "body": body, "data": data or {}}, ensure_ascii=False)
    results = await asyncio.gather(*(_send_one(t, s, payload) for t, s in subs))
    dead = [t for (t, _), state in zip(subs, results) if state == "gone"]
    if dead:
        await _forget(dead)
    return "sent" if "ok" in results else "failed"


async def send(tokens: list[str], title: str, body: str, data: dict[str, str] | None = None) -> str:
    """Send to [tokens]. Returns the status to record: "sent", "dry_run",
    "no_device" (nothing in [tokens] this mode can deliver to) or "failed"."""
    mode = settings.push_mode
    if mode == "dry_run":
        log.info("push (dry run) to %d device(s): %s | %s", len(tokens), title, body)
        return "dry_run"
    if mode == "web":
        if not web_push_ready():
            raise PushUnavailable("web push needs VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY")
        return await _send_web(tokens, title, body, data)
    raise PushUnavailable(f"push mode {mode!r} has no provider yet")
