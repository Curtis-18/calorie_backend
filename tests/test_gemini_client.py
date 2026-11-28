import httpx
import pytest

from app.services import gemini_client
from app.services.insights_service import degraded_insights


class _FakeResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.request = httpx.Request("POST", "https://gemini.test")

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "upstream error", request=self.request, response=self
            )


class _FakeClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, *args, **kwargs):
        self.calls += 1
        return self._responses.pop(0)


@pytest.fixture
def no_sleep(monkeypatch):
    async def _sleep(_seconds):
        return None

    monkeypatch.setattr(gemini_client.asyncio, "sleep", _sleep)


def _install(monkeypatch, responses):
    client = _FakeClient(responses)
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: client)
    return client


async def test_retries_transient_503_then_succeeds(monkeypatch, no_sleep):
    """The exact failure from the Render log: a 503 under high demand."""
    client = _install(
        monkeypatch,
        [
            _FakeResponse(503, text="high demand"),
            _FakeResponse(200, payload={"candidates": [{"content": {"parts": []}}]}),
        ],
    )
    data = await gemini_client.generate_content({"contents": []})
    assert data["candidates"] == [{"content": {"parts": []}}]
    assert client.calls == 2


async def test_gives_up_after_max_attempts(monkeypatch, no_sleep):
    client = _install(monkeypatch, [_FakeResponse(503, text="down")] * 3)
    with pytest.raises(httpx.HTTPStatusError):
        await gemini_client.generate_content({"contents": []})
    assert client.calls == gemini_client.MAX_ATTEMPTS


async def test_non_retryable_error_does_not_retry(monkeypatch, no_sleep):
    """A 400 (bad key/schema) fails the same way every time."""
    client = _install(monkeypatch, [_FakeResponse(400, text="bad request")])
    with pytest.raises(httpx.HTTPStatusError):
        await gemini_client.generate_content({"contents": []})
    assert client.calls == 1


def test_degraded_insights_keeps_the_local_trend():
    trend = [
        {"date": "2026-10-11", "calories": 1200, "protein_g": 80.0, "carbs_g": 0, "fat_g": 0}
    ]
    payload = degraded_insights(trend)
    assert payload["weekly_trend"] is trend
    assert payload["narrative"]
    assert payload["tips"] == []  # removed from the app; the key stays so older copies do not break


@pytest.mark.parametrize("status", [429, 500, 502, 504])
async def test_only_503_is_retried(monkeypatch, no_sleep, status):
    """A spent quota (429) must not be hammered; the others are not worth a
    second paid attempt either."""
    client = _install(monkeypatch, [_FakeResponse(status, text="nope")] * 3)
    with pytest.raises(httpx.HTTPStatusError):
        await gemini_client.generate_content({"contents": []})
    assert client.calls == 1


class _RecordingClient(_FakeClient):
    def __init__(self, responses):
        super().__init__(responses)
        self.bodies = []

    async def post(self, *args, **kwargs):
        self.bodies.append(kwargs.get("json"))
        return await super().post(*args, **kwargs)


@pytest.fixture
def thinking_state(monkeypatch):
    monkeypatch.setattr(gemini_client, "_thinking_rejected", False)


def _record(monkeypatch, responses):
    client = _RecordingClient(responses)
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: client)
    return client


@pytest.mark.parametrize(
    "model,expected",
    [
        ("gemini-3.6-flash", {"thinkingLevel": "low"}),
        ("gemini-2.5-flash", {"thinkingBudget": 0}),
        ("gemini-2.5-pro", {"thinkingBudget": 128}),
        ("some-other-model", None),
    ],
)
def test_thinking_config_follows_the_model(model, expected):
    assert gemini_client.thinking_config(model) == expected


async def test_thinking_is_limited_without_touching_the_callers_payload(monkeypatch, thinking_state):
    monkeypatch.setattr(gemini_client.settings, "gemini_model", "gemini-3.6-flash")
    client = _record(monkeypatch, [_FakeResponse(200, payload={})])
    payload = {"contents": [], "generationConfig": {"response_mime_type": "application/json"}}
    await gemini_client.generate_content(payload)
    sent = client.bodies[0]["generationConfig"]
    assert sent["thinkingConfig"] == {"thinkingLevel": "low"}
    assert sent["response_mime_type"] == "application/json"
    assert "thinkingConfig" not in payload["generationConfig"]


async def test_a_rejected_thinking_parameter_is_dropped_and_the_call_still_works(
    monkeypatch, no_sleep, thinking_state
):
    """A wrong guess about the parameter must not break scans."""
    monkeypatch.setattr(gemini_client.settings, "gemini_model", "gemini-3.6-flash")
    client = _record(
        monkeypatch,
        [
            _FakeResponse(400, text='Invalid JSON payload: Unknown name "thinkingLevel"; thinking is not supported'),
            _FakeResponse(200, payload={"ok": 1}),
            _FakeResponse(200, payload={"ok": 2}),
        ],
    )
    assert (await gemini_client.generate_content({"contents": []}))["ok"] == 1
    assert "thinkingConfig" in client.bodies[0]["generationConfig"]
    assert "generationConfig" not in client.bodies[1]
    # ...and it is not sent again.
    await gemini_client.generate_content({"contents": []})
    assert "generationConfig" not in client.bodies[2]


async def test_an_unrelated_400_is_not_mistaken_for_a_thinking_problem(
    monkeypatch, no_sleep, thinking_state
):
    monkeypatch.setattr(gemini_client.settings, "gemini_model", "gemini-3.6-flash")
    client = _record(monkeypatch, [_FakeResponse(400, text="API key not valid")])
    with pytest.raises(httpx.HTTPStatusError):
        await gemini_client.generate_content({"contents": []})
    assert client.calls == 1
    assert gemini_client._thinking_rejected is False


async def test_each_paid_call_logs_its_tokens(monkeypatch, caplog, thinking_state):
    import logging

    _install(
        monkeypatch,
        [
            _FakeResponse(
                200,
                payload={
                    "usageMetadata": {
                        "promptTokenCount": 1200,
                        "candidatesTokenCount": 80,
                        "thoughtsTokenCount": 15,
                    }
                },
            )
        ],
    )
    with caplog.at_level(logging.INFO, logger="calorie_backend"):
        await gemini_client.generate_content(
            {"contents": [{"parts": [{"text": "hi"}, {"inline_data": {"data": "x"}}]}]}
        )
    line = next(r.getMessage() for r in caplog.records if "gemini_call" in r.getMessage())
    assert "kind=scan" in line
    assert "prompt_tokens=1200" in line and "output_tokens=80" in line and "thought_tokens=15" in line


def test_the_hourly_limits_are_tight():
    from app.core import rate_limit

    assert rate_limit.photo_scans.limit == 20
    assert rate_limit.insight_generations.limit == 6


async def test_an_explicit_kind_names_the_call_in_the_log(monkeypatch, caplog, thinking_state):
    import logging

    _install(monkeypatch, [_FakeResponse(200, payload={"usageMetadata": {"promptTokenCount": 5}})])
    with caplog.at_level(logging.INFO, logger="calorie_backend"):
        await gemini_client.generate_content({"contents": []}, kind="coach")
    assert any("kind=coach" in r.getMessage() for r in caplog.records)


# ---- streaming (the coach, since 28 Nov 2026) --------------------------------------------------------

class _StreamResponse:
    def __init__(self, status_code, lines=(), text="", drop_after=None):
        self.status_code = status_code
        self._lines = list(lines)
        self.text = text
        self.drop_after = drop_after
        self.request = httpx.Request("POST", "https://gemini.test")

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def aread(self):
        return self.text.encode()

    async def aiter_lines(self):
        for n, line in enumerate(self._lines):
            if self.drop_after is not None and n == self.drop_after:
                raise httpx.ReadError("connection dropped")
            yield line


class _StreamClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def stream(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self._responses.pop(0)


def _streams(monkeypatch, responses):
    client = _StreamClient(responses)
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: client)
    return client


def _sse(text, finish=None, usage=None):
    import json as _json

    chunk = {"candidates": [{"content": {"parts": [{"text": text}]}}]}
    if finish:
        chunk["candidates"][0]["finishReason"] = finish
    if usage:
        chunk["usageMetadata"] = usage
    return "data: " + _json.dumps(chunk)


async def _collect(payload=None, **kw):
    return [c async for c in gemini_client.stream_content(payload or {"contents": []}, kind="coach", **kw)]


async def test_a_stream_passes_each_piece_on_in_order_and_skips_what_is_not_a_piece(monkeypatch, caplog, thinking_state):
    import logging

    monkeypatch.setattr(gemini_client.settings, "gemini_model", "gemini-3.6-flash")
    client = _streams(monkeypatch, [_StreamResponse(200, [
        _sse("Nice "), "", ": a comment", "event: message", "data: not json", "data: [1, 2]",
        _sse("work today."), _sse("", finish="STOP", usage={"promptTokenCount": 900, "candidatesTokenCount": 40}),
        "data: [DONE]",
    ])])
    with caplog.at_level(logging.INFO, logger="calorie_backend"):
        chunks = await _collect()
    texts = [c["candidates"][0]["content"]["parts"][0]["text"] for c in chunks]
    assert texts == ["Nice ", "work today.", ""]
    method, url, kwargs = client.calls[0]
    assert method == "POST" and url.endswith("/models/gemini-3.6-flash:streamGenerateContent?alt=sse")
    assert "key=" not in url and kwargs["headers"]["x-goog-api-key"] is not None
    assert kwargs["json"]["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "low"}
    line = next(r.getMessage() for r in caplog.records if r.getMessage().startswith("gemini_call"))
    assert "kind=coach" in line and "prompt_tokens=900" in line and "output_tokens=40" in line


async def test_a_stream_counts_against_the_shared_daily_budget(monkeypatch, thinking_state):
    from app.services import gemini_budget

    seen = []
    monkeypatch.setattr(gemini_budget, "record_call", lambda model=None: seen.append(model))
    _streams(monkeypatch, [_StreamResponse(200, [_sse("Hi.")])])
    await _collect()
    assert len(seen) == 1


async def test_a_spent_budget_refuses_a_stream_before_anything_is_sent(monkeypatch, thinking_state):
    from app.services import gemini_budget

    def refuse(kind, now=None, model=None):
        raise RuntimeError("budget spent")

    monkeypatch.setattr(gemini_budget, "check", refuse)
    client = _streams(monkeypatch, [])
    with pytest.raises(RuntimeError):
        await _collect()
    assert client.calls == []


async def test_a_busy_model_is_asked_again_before_the_first_piece(monkeypatch, no_sleep, thinking_state):
    client = _streams(monkeypatch, [_StreamResponse(503, text="high demand"), _StreamResponse(200, [_sse("Hi.")])])
    assert len(await _collect()) == 1 and len(client.calls) == 2


async def test_a_spent_quota_on_a_stream_is_not_asked_again(monkeypatch, no_sleep, thinking_state):
    from app.services import gemini_budget

    noted = []
    monkeypatch.setattr(gemini_budget, "note_rejected", lambda body, now=None, model=None: noted.append(body))
    client = _streams(monkeypatch, [_StreamResponse(429, text="quota exceeded")])
    with pytest.raises(httpx.HTTPStatusError):
        await _collect()
    assert len(client.calls) == 1 and noted == ["quota exceeded"]


async def test_a_stream_whose_thinking_setting_is_refused_is_sent_again_without_it(monkeypatch, no_sleep, thinking_state):
    monkeypatch.setattr(gemini_client.settings, "gemini_model", "gemini-3.6-flash")
    client = _streams(monkeypatch, [
        _StreamResponse(400, text='Unknown name "thinkingLevel": thinking is not supported'),
        _StreamResponse(200, [_sse("Hi.")]),
    ])
    assert len(await _collect()) == 1
    assert "thinkingConfig" in client.calls[0][2]["json"]["generationConfig"]
    assert "generationConfig" not in client.calls[1][2]["json"]


async def test_a_connection_that_drops_after_a_piece_is_not_asked_again(monkeypatch, no_sleep, thinking_state):
    """Asking again would show the same words twice; the caller decides instead."""
    client = _streams(monkeypatch, [_StreamResponse(200, [_sse("Hi. "), _sse("More.")], drop_after=1)])
    got = []
    with pytest.raises(httpx.ReadError):
        async for chunk in gemini_client.stream_content({"contents": []}, kind="coach"):
            got.append(chunk)
    assert len(got) == 1 and len(client.calls) == 1


async def test_a_connection_that_fails_before_any_piece_is_tried_again(monkeypatch, no_sleep, thinking_state):
    client = _streams(monkeypatch, [_StreamResponse(200, [_sse("x")], drop_after=0), _StreamResponse(200, [_sse("Hi.")])])
    assert len(await _collect()) == 1 and len(client.calls) == 2


async def test_when_the_main_models_quota_is_spent_the_stream_uses_the_fallback_model(monkeypatch, no_sleep, thinking_state):
    monkeypatch.setattr(gemini_client.settings, "gemini_model", "gemini-3.6-flash")
    monkeypatch.setattr(gemini_client.settings, "gemini_fallback_model", "gemini-2.5-flash")
    client = _streams(monkeypatch, [_StreamResponse(429, text="RESOURCE_EXHAUSTED quota"), _StreamResponse(200, [_sse("Hi.")])])
    assert len(await _collect()) == 1
    assert "gemini-2.5-flash:streamGenerateContent" in client.calls[1][1]
