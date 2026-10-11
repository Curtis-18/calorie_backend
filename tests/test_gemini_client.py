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
