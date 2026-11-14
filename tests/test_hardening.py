"""Regression tests for the security and robustness fixes of 14 Nov 2026."""

import base64
import uuid

import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

ME = uuid.UUID("00000000-0000-0000-0000-000000000001")


# --- request body limit ------------------------------------------------------

def test_oversized_body_is_refused_without_auth(anon_client):
    """The body is read before auth runs, so the limit must not need a token."""
    r = anon_client.post("/estimate-photo", content=b"x" * 12_000_000, headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_oversized_body_without_content_length_is_refused(anon_client):
    def chunks():
        for _ in range(12):
            yield b"x" * 1_000_000

    r = anon_client.post("/estimate-photo", content=chunks(), headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_413_keeps_cors_headers(anon_client):
    r = anon_client.post(
        "/estimate-photo", content=b"x" * 12_000_000,
        headers={"Content-Type": "application/json", "Origin": "https://app.example.com"},
    )
    assert r.status_code == 413
    assert r.headers["access-control-allow-origin"] == "https://app.example.com"


def test_normal_photo_body_passes_the_limit(client, monkeypatch):
    from app.routers import photo_estimation

    async def nothing(*a, **k):
        return []

    monkeypatch.setattr(photo_estimation, "identify_foods", nothing)
    photo = b"\xff\xd8\xff" + b"x" * 3_000_000
    r = client.post("/estimate-photo", json={"image": base64.b64encode(photo).decode()})
    assert r.status_code == 200


# --- auth: an outage is not a bad session -------------------------------------

async def test_jwks_outage_is_503_not_401(monkeypatch):
    from fastapi.security import HTTPAuthorizationCredentials
    from jwt.exceptions import PyJWKClientConnectionError

    from app.core import security

    def boom(_creds):
        raise PyJWKClientConnectionError("could not fetch keys")

    monkeypatch.setattr(security, "_decode", boom)
    with pytest.raises(HTTPException) as exc:
        await security.verify_token(HTTPAuthorizationCredentials(scheme="Bearer", credentials="x.y.z"))
    assert exc.value.status_code == 503


def test_bad_token_is_still_401(anon_client, monkeypatch):
    import jwt

    from app.core import security

    def bad(_creds):
        raise jwt.InvalidTokenError("nope")

    monkeypatch.setattr(security, "_decode", bad)
    assert anon_client.get("/targets", headers={"Authorization": "Bearer x.y.z"}).status_code == 401


# --- API keys stay out of URLs (and so out of logs) -----------------------------

async def test_usda_key_is_sent_as_a_header(monkeypatch):
    from app.services import usda_service

    seen = {}
    real = httpx.AsyncClient

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["key"] = request.headers.get("x-api-key")
        return httpx.Response(500, text="boom")

    monkeypatch.setattr(usda_service.httpx, "AsyncClient", lambda *a, **kw: real(*a, **{**kw, "transport": httpx.MockTransport(handler)}))
    with pytest.raises(httpx.HTTPStatusError) as exc:
        await usda_service.search_foods("apple")
    assert seen["key"] == "test-usda"
    assert "test-usda" not in seen["url"] and "api_key" not in seen["url"]
    assert "test-usda" not in str(exc.value)


async def test_gemini_key_is_sent_as_a_header(monkeypatch):
    from app.services import gemini_client

    seen = {}
    real = httpx.AsyncClient

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["key"] = request.headers.get("x-goog-api-key")
        return httpx.Response(400, text="bad")

    monkeypatch.setattr(gemini_client.httpx, "AsyncClient", lambda *a, **kw: real(*a, **{**kw, "transport": httpx.MockTransport(handler)}))
    with pytest.raises(httpx.HTTPStatusError) as exc:
        await gemini_client.generate_content({})
    assert seen["key"] == "test-gemini"
    assert "test-gemini" not in seen["url"] and "key=" not in seen["url"]
    assert "test-gemini" not in str(exc.value)


# --- input bounds ---------------------------------------------------------------

def _log(**over):
    from app.schemas.food_log import FoodLogIn

    return FoodLogIn(**{
        "id": "e1", "name": "Apple", "calories": 95, "meal_type": "snack", "source": "manual",
        "timestamp": "2026-11-02T08:00:00", "log_date": "2026-11-02", **over,
    })


@pytest.mark.parametrize("field,value", [
    ("protein_g", float("inf")), ("carbs_g", float("nan")), ("fat_g", 1e9),
    ("calories", 10**12), ("name", ""), ("name", "x" * 501), ("id", ""), ("id", "x" * 301),
])
def test_food_log_rejects_absurd_values(field, value):
    with pytest.raises(ValidationError):
        _log(**{field: value})


def test_food_log_timestamp_with_an_offset_is_stored_as_naive_utc():
    assert _log(timestamp="2026-11-02T08:00:00+03:00").timestamp.isoformat() == "2026-11-02T05:00:00"
    assert _log(timestamp="2026-11-02T08:00:00Z").timestamp.tzinfo is None
    # What the app sends: local time, no offset, kept exactly.
    assert _log(timestamp="2026-11-02T08:00:00.123").timestamp.isoformat() == "2026-11-02T08:00:00.123000"


def _onboarding(**over):
    from app.schemas.target import OnboardingIn

    return OnboardingIn(**{
        "date_of_birth": "1995-03-14", "sex": "male", "height_feet": 5, "height_inches": 10,
        "weight_value": 75, "weight_unit": "kg", "activity_level": "moderate", "goal": "maintain", **over,
    })


@pytest.mark.parametrize("over", [
    {"weight_value": 1e300}, {"weight_value": 0.01}, {"weight_value": 900, "weight_unit": "lb"},
    {"weight_value": float("inf")}, {"date_of_birth": "0001-01-01"},
])
def test_onboarding_rejects_implausible_bodies(over):
    with pytest.raises(ValidationError):
        _onboarding(**over)


@pytest.mark.parametrize("over", [
    {"weight_value": 20}, {"weight_value": 400}, {"weight_value": 881.8, "weight_unit": "lb"},
    {"weight_value": 44.1, "weight_unit": "lb"},
])
def test_onboarding_accepts_everything_the_app_allows(over):
    _onboarding(**over)


def test_implausible_onboarding_is_a_422(client):
    r = client.post("/targets", json={
        "date_of_birth": "1995-03-14", "sex": "male", "height_feet": 5, "height_inches": 10,
        "weight_value": 1e300, "weight_unit": "kg", "activity_level": "moderate", "goal": "maintain",
    })
    assert r.status_code == 422


# --- log ids with awkward characters ----------------------------------------------

def test_log_id_containing_a_slash_can_be_deleted_and_edited(client):
    from types import SimpleNamespace

    from app.core.database import get_db
    from app.main import app

    seen = []
    entry = SimpleNamespace(
        id="1_0_Mac/cheese?", user_id=ME, name="Mac", calories=1, protein_g=0, carbs_g=0, fat_g=0,
        meal_type="snack", source="photo", timestamp="2026-11-02T08:00:00", log_date="2026-11-02",
    )

    class Db:
        async def get(self, _model, pk):
            seen.append(pk)
            return entry if pk == entry.id else None

        async def delete(self, _obj):
            pass

        async def commit(self):
            pass

        async def rollback(self):
            pass

        def begin_nested(self):
            raise RuntimeError("no nutrients table in this fake")

    async def fake_db():
        yield Db()

    app.dependency_overrides[get_db] = fake_db
    assert client.patch("/logs/1_0_Mac%2Fcheese%3F", json={"calories": 5}).status_code == 200
    assert client.delete("/logs/1_0_Mac%2Fcheese%3F").status_code == 204
    assert seen == [entry.id, entry.id]
    # The day's list is still its own route.
    assert client.patch("/logs/today", json={"calories": 5}).status_code == 404


# --- rate limits ---------------------------------------------------------------------

def test_rate_limit_window():
    from app.core.rate_limit import RateLimit

    limit = RateLimit(2, 60)
    other = uuid.uuid4()
    assert limit.allow("x", ME, now=0) and limit.allow("x", ME, now=1)
    assert not limit.allow("x", ME, now=2)
    assert limit.allow("x", other, now=2)  # per person
    assert limit.allow("y", ME, now=2)  # per endpoint
    assert limit.allow("x", ME, now=61)  # the first hit has aged out


def test_photo_scans_are_rate_limited(client, monkeypatch):
    from app.core import rate_limit
    from app.routers import photo_estimation

    async def nothing(*a, **k):
        return []

    monkeypatch.setattr(photo_estimation, "identify_foods", nothing)
    monkeypatch.setattr(photo_estimation, "photo_scans", rate_limit.RateLimit(1, 3600))
    body = {"image": base64.b64encode(b"\xff\xd8\xffjpeg").decode()}
    assert client.post("/estimate-photo", json=body).status_code == 200
    r = client.post("/estimate-photo", json=body)
    assert r.status_code == 429 and "scanned" in r.json()["detail"]


# --- cron secret -----------------------------------------------------------------------

def test_cron_secret_with_odd_bytes_is_403_not_500(anon_client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "cron_secret", "s3cret")
    for path in ("/snaps/purge", "/notifications/cron/streak-reminders"):
        r = anon_client.post(path, headers={"X-Cron-Secret": b"caf\xe9"})
        assert r.status_code == 403, path
