"""Refuse request bodies that are too large before they are read into memory.

FastAPI reads and parses the whole JSON body before any dependency runs, auth
included. The per-endpoint photo size checks therefore only ran after the
payload was already in memory, and anyone (no account needed) could post
hundreds of megabytes and take down a 512 MB instance.
"""

import json


class BodyTooLarge(Exception):
    pass


class BodyLimitMiddleware:
    def __init__(self, app, max_bytes: int):
        self.app = app
        self.max_bytes = max_bytes

    async def _reject(self, send) -> None:
        body = json.dumps({"detail": "That request is too large."}).encode()
        await send({
            "type": "http.response.start",
            "status": 413,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        })
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        declared = dict(scope.get("headers") or []).get(b"content-length")
        if declared is not None:
            try:
                too_big = int(declared) > self.max_bytes
            except ValueError:
                too_big = True
            if too_big:
                return await self._reject(send)

        # No (or a dishonest) Content-Length: count what actually arrives.
        seen = 0
        exceeded = False
        started = False

        async def limited_receive():
            nonlocal seen, exceeded
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body") or b"")
                if seen > self.max_bytes:
                    exceeded = True
                    raise BodyTooLarge
            return message

        async def tracking_send(message):
            nonlocal started
            if exceeded and not started:
                return  # the app's own error for the aborted read; ours replaces it
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except BodyTooLarge:
            pass
        if exceeded and not started:
            await self._reject(send)
