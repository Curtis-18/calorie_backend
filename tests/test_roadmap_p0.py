"""Roadmap P0: scan timing log, the feature gate and usage counter, barcode lookup."""

import base64
import logging
import uuid
from datetime import date

import httpx
import pytest

from app.core import features
from app.core.features import Feature
from app.services import usda_service
from app.services.usda_service import normalize_barcode

ME = uuid.UUID("00000000-0000-0000-0000-000000000001")
PHOTO = base64.b64encode(b"\xff\xd8\xffjpeg").decode()


@pytest.fixture(autouse=True)
def _fresh_limits():
    from app.core.rate_limit import food_searches, photo_scans

    photo_scans.reset()
    food_searches.reset()
    yield


# ---- feature gate and usage counter --------------------------------------

def test_every_feature_is_allowed_for_now():
    for feature in Feature:
        assert features.require_feature(ME, feature) is None
    assert all(limit is None for limit in features.FREE_DAILY_LIMITS.values())
    assert set(features.FREE_DAILY_LIMITS) == set(Feature)


@pytest.mark.asyncio
async def test_record_usage_upserts_one_row_for_the_day(usage_db):
    await features.record_usage(ME, Feature.PHOTO_SCAN, date(2026, 11, 18))
    assert len(usage_db.statements) == 1
    sql = str(usage_db.statements[0].compile(dialect=__import__("sqlalchemy.dialects.postgresql", fromlist=["x"]).dialect()))
    assert "INSERT INTO ai_usage" in sql
    assert "ON CONFLICT (user_id, day, feature) DO UPDATE" in sql


@pytest.mark.asyncio
async def test_record_usage_never_raises(usage_db, caplog):
    usage_db.fail = True  # e.g. the migration has not been run yet
    with caplog.at_level(logging.WARNING, logger="calorie_backend"):
        await features.record_usage(ME, Feature.PHOTO_SCAN, date(2026, 11, 18))
    assert "ai usage not recorded" in caplog.text


# ---- photo route: timing line and counting --------------------------------

def _fake_scan(monkeypatch, items):
    from app.routers import photo_estimation as route

    async def identify(image_bytes, mime_type):
        return [{"name": "rice", "estimated_grams": 150}]

    async def enrich(detected):
        return items

    monkeypatch.setattr(route, "identify_foods", identify)
    monkeypatch.setattr(route, "enrich_detected_foods", enrich)


def test_scan_logs_one_timing_line_without_food_names(client, monkeypatch, caplog):
    _fake_scan(monkeypatch, [
        {"name": "rice", "estimated_grams": 150, "matched": True},
        {"name": "mystery stew", "estimated_grams": 200, "matched": False},
    ])
    with caplog.at_level(logging.INFO, logger="calorie_backend"):
        r = client.post("/estimate-photo", json={"image": PHOTO})
    assert r.status_code == 200
    line = next(m for m in caplog.messages if m.startswith("scan_done"))
    assert "status=ok" in line and "items=2" in line and "matched=1" in line
    for key in ("ms_total=", "ms_gemini=", "ms_usda="):
        assert key in line
    assert "rice" not in line and "stew" not in line


def test_successful_scan_is_counted_on_the_clients_date(client, monkeypatch, usage_db):
    _fake_scan(monkeypatch, [{"name": "rice", "estimated_grams": 150, "matched": True}])
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).date()
    assert client.post("/estimate-photo", json={"image": PHOTO, "date": today.isoformat()}).status_code == 200
    assert len(usage_db.statements) == 1
    params = usage_db.statements[0].compile().params
    assert params["day"] == today and params["feature"] == "photo_scan" and params["user_id"] == ME


def test_failed_scan_is_not_counted(client, monkeypatch, usage_db, caplog):
    from app.routers import photo_estimation as route

    async def boom(*a, **k):
        raise RuntimeError("gemini down")

    monkeypatch.setattr(route, "identify_foods", boom)
    with caplog.at_level(logging.INFO, logger="calorie_backend"):
        r = client.post("/estimate-photo", json={"image": PHOTO})
    assert r.status_code == 502
    assert usage_db.statements == []
    assert any(m.startswith("scan_done status=gemini_failed") for m in caplog.messages)


def test_scan_date_must_be_a_real_local_date(client, monkeypatch):
    _fake_scan(monkeypatch, [])
    assert client.post("/estimate-photo", json={"image": PHOTO, "date": "2001-01-01"}).status_code == 422


def test_scan_without_a_date_still_works_for_older_clients(client, monkeypatch):
    _fake_scan(monkeypatch, [])
    assert client.post("/estimate-photo", json={"image": PHOTO}).status_code == 200


# ---- barcode ---------------------------------------------------------------

@pytest.mark.parametrize("code,ok", [
    ("012345678905", True), ("4006381333931", True), ("96385074", True),
    ("1234567", False), ("123456789012345", False), ("12345abc9012", False),
    ("", False), ("١٢٣٤٥٦٧٨٩٠١٢", False), (" 012345678905 ", True),
])
def test_barcode_shape(code, ok):
    assert (normalize_barcode(code) is not None) is ok


def _usda(foods):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["query"]
        assert "api_key" not in str(request.url)
        return httpx.Response(200, json={"foods": foods})

    return handler


def _patch_http(monkeypatch, handler):
    real = httpx.AsyncClient

    def factory(*a, **k):
        k["transport"] = httpx.MockTransport(handler)
        return real(*a, **k)

    monkeypatch.setattr(usda_service.httpx, "AsyncClient", factory)


def _branded(upc, **extra):
    return {
        "fdcId": 111, "description": "OAT BAR", "dataType": "Branded", "gtinUpc": upc,
        "foodNutrients": [
            {"nutrientName": "Energy", "unitName": "KCAL", "value": 400},
            {"nutrientName": "Protein", "unitName": "G", "value": 10},
            {"nutrientName": "Total lipid (fat)", "unitName": "G", "value": 15},
            {"nutrientName": "Carbohydrate, by difference", "unitName": "G", "value": 55},
        ], **extra,
    }


def test_barcode_found(client, monkeypatch):
    _patch_http(monkeypatch, _usda([_branded("012345678905")]))
    r = client.get("/foods/barcode", params={"code": "012345678905"})
    assert r.status_code == 200
    body = r.json()
    assert body["description"] == "OAT BAR" and body["calories_per_100g"] == 400


def test_barcode_matches_upc_and_ean_forms_of_the_same_code(client, monkeypatch):
    _patch_http(monkeypatch, _usda([_branded("12345678905")]))
    assert client.get("/foods/barcode", params={"code": "0012345678905"}).status_code == 200


def test_barcode_ignores_hits_for_a_different_code(client, monkeypatch):
    _patch_http(monkeypatch, _usda([_branded("999999999999")]))
    assert client.get("/foods/barcode", params={"code": "012345678905"}).status_code == 404


def test_barcode_not_found(client, monkeypatch):
    _patch_http(monkeypatch, _usda([]))
    r = client.get("/foods/barcode", params={"code": "012345678905"})
    assert r.status_code == 404 and "searching by name" in r.json()["detail"]


def test_barcode_rejects_non_barcodes_without_calling_usda(client, monkeypatch):
    def handler(request):
        raise AssertionError("USDA must not be called")

    _patch_http(monkeypatch, handler)
    assert client.get("/foods/barcode", params={"code": "hello"}).status_code == 422
    assert client.get("/foods/barcode", params={"code": "123"}).status_code == 422


def test_barcode_upstream_failure_is_502(client, monkeypatch):
    _patch_http(monkeypatch, lambda request: httpx.Response(500, text="boom"))
    assert client.get("/foods/barcode", params={"code": "012345678905"}).status_code == 502


def test_barcode_skips_a_broken_branded_entry(client, monkeypatch):
    broken = _branded("012345678905")
    broken["foodNutrients"][0]["value"] = 0  # 0 kcal with 10/15/55 g of macros
    _patch_http(monkeypatch, _usda([broken]))
    assert client.get("/foods/barcode", params={"code": "012345678905"}).status_code == 404


def test_barcode_needs_a_login(anon_client):
    assert anon_client.get("/foods/barcode", params={"code": "012345678905"}).status_code == 401


def test_barcode_shares_the_search_rate_limit(client, monkeypatch):
    from app.core.rate_limit import food_searches

    _patch_http(monkeypatch, _usda([]))
    for _ in range(food_searches.limit):
        client.get("/foods/barcode", params={"code": "012345678905"})
    assert client.get("/foods/barcode", params={"code": "012345678905"}).status_code == 429


def test_barcode_is_searched_in_every_spelling_usda_may_store():
    from app.services.usda_service import barcode_forms

    assert barcode_forms("016000275287") == ["016000275287", "0016000275287", "00016000275287"]
    assert "00016000275287" in barcode_forms("016000275287")
    assert barcode_forms("4006381333931") == ["4006381333931", "04006381333931"]
    assert len(barcode_forms("96385074")) == 4  # EAN-8 plus its three padded forms


def test_barcode_found_when_usda_only_has_the_padded_form(client, monkeypatch):
    def handler(request):
        asked = request.url.params["query"]
        return httpx.Response(200, json={"foods": [_branded("00016000275287")] if asked == "00016000275287" else []})

    _patch_http(monkeypatch, handler)
    assert client.get("/foods/barcode", params={"code": "016000275287"}).status_code == 200
