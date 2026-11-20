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
    assert payload["tips"]


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
