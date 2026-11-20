"""Roadmap P1.1: preparation/kind from the photo, and the one-tap extras."""

import pytest

from app.models.food import FoodSearchResult
from app.services import adjustments
from app.services.gemini_service import _extract_items


@pytest.fixture(autouse=True)
def _fresh():
    adjustments.reset_cache()
    yield
    adjustments.reset_cache()


def _data(items):
    import json

    return {"candidates": [{"content": {"parts": [{"text": json.dumps(items)}]}}]}


def test_preparation_and_kind_are_kept_when_they_are_known_words():
    out = _extract_items(_data([{"name": "Fish", "estimated_grams": 120, "preparation": "Fried", "kind": "main"}]))
    assert out == [{"name": "Fish", "estimated_grams": 120.0, "preparation": "fried", "kind": "main"}]


def test_unknown_words_are_dropped_not_passed_on():
    out = _extract_items(_data([{"name": "Fish", "estimated_grams": 120, "preparation": "deep-fried in lard", "kind": 7}]))
    assert out == [{"name": "Fish", "estimated_grams": 120.0}]


def test_scan_response_carries_preparation_and_kind(client, monkeypatch):
    import base64

    from app.routers import photo_estimation as route

    async def identify(image_bytes, mime_type):
        return [{"name": "fish", "estimated_grams": 100, "preparation": "fried", "kind": "main"}]

    async def enrich(items):
        return [{**i, "matched": True} for i in items]

    monkeypatch.setattr(route, "identify_foods", identify)
    monkeypatch.setattr(route, "enrich_detected_foods", enrich)
    r = client.post("/estimate-photo", json={"image": base64.b64encode(b"\xff\xd8\xffx").decode()})
    assert r.json()[0]["preparation"] == "fried" and r.json()[0]["kind"] == "main"


def _result(fdc, kcal):
    return FoodSearchResult(fdc_id=fdc, description="x", calories_per_100g=kcal, protein_g_per_100g=0,
                            carbs_g_per_100g=0, fat_g_per_100g=100)


def _fake_usda(monkeypatch, kcal_by_query):
    async def best(query):
        k = kcal_by_query.get(query)
        return None if k is None else _result(1, k)

    monkeypatch.setattr(adjustments, "get_best_match", best)


def _plausible():
    return {e.query: (e.kcal_range[0] + e.kcal_range[1]) / 2 for e in adjustments.EXTRAS}


@pytest.mark.asyncio
async def test_every_extra_gets_numbers_from_usda_and_the_scale_chip_is_added(monkeypatch):
    _fake_usda(monkeypatch, _plausible())
    result = await adjustments.list_adjustments()
    ids = [r["id"] for r in result]
    assert ids == ["oil", "butter", "dressing", "cheese", "sugar", "restaurant"]
    oil = result[0]
    assert oil["kind"] == "add" and oil["grams"] == 14 and oil["calories_per_100g"] == 860
    assert "fried" in oil["preparations"]
    assert result[-1]["kind"] == "scale" and result[-1]["factor"] == adjustments.RESTAURANT_FACTOR


@pytest.mark.asyncio
async def test_an_implausible_match_is_dropped_so_no_wrong_number_reaches_a_log(monkeypatch):
    kcal = _plausible()
    kcal["Oil, vegetable, soybean, refined"] = 90  # e.g. matched to "oil-free dressing"
    _fake_usda(monkeypatch, kcal)
    ids = [r["id"] for r in await adjustments.list_adjustments()]
    assert "oil" not in ids and "butter" in ids


@pytest.mark.asyncio
async def test_a_complete_answer_is_remembered_and_an_incomplete_one_is_retried(monkeypatch):
    calls = []

    async def best(query):
        calls.append(query)
        return None if query == "Butter, salted" and len(calls) <= len(adjustments.EXTRAS) else _result(1, _plausible()[query])

    monkeypatch.setattr(adjustments, "get_best_match", best)
    first = await adjustments.list_adjustments()
    assert "butter" not in [r["id"] for r in first]
    second = await adjustments.list_adjustments()  # retried, now complete
    assert "butter" in [r["id"] for r in second]
    n = len(calls)
    await adjustments.list_adjustments()
    assert len(calls) == n  # remembered


@pytest.mark.asyncio
async def test_a_usda_outage_just_means_fewer_chips(monkeypatch):
    async def boom(query):
        raise RuntimeError("usda down")

    monkeypatch.setattr(adjustments, "get_best_match", boom)
    result = await adjustments.list_adjustments()
    assert [r["id"] for r in result] == ["restaurant"]


def test_route_returns_the_list(client, monkeypatch):
    _fake_usda(monkeypatch, _plausible())
    r = client.get("/adjustments")
    assert r.status_code == 200 and r.json()[0]["id"] == "oil"


def test_route_needs_a_login(anon_client):
    assert anon_client.get("/adjustments").status_code == 401


# ---- P1.2: the spoken note -------------------------------------------------

def test_added_extras_and_reasons_are_kept_only_when_valid():
    out = _extract_items(_data([{
        "name": "Fish", "estimated_grams": 60, "added": ["Butter", "butter", "rm -rf", 5, "oil"],
        "note_applied": "  Halved because you said half  ",
    }]))
    assert out[0]["added"] == ["butter", "oil"]
    assert out[0]["note_applied"] == "Halved because you said half"


def test_no_note_means_the_prompt_is_unchanged():
    import asyncio

    from app.services import gemini_service

    sent = []

    async def fake(payload, **kwargs):
        sent.append(payload["contents"][0]["parts"][0]["text"])
        return _data([])

    gemini_service.generate_content, original = fake, gemini_service.generate_content
    try:
        asyncio.run(gemini_service.identify_foods(b"x", "image/jpeg"))
        asyncio.run(gemini_service.identify_foods(b"x", "image/jpeg", note="half of this"))
    finally:
        gemini_service.generate_content = original
    assert "NOT instructions" not in sent[0]
    assert "half of this" in sent[1] and "NOT instructions" in sent[1]


def test_the_note_reaches_the_model_and_is_bounded(client, monkeypatch):
    import base64

    from app.routers import photo_estimation as route

    seen = {}

    async def identify(image_bytes, mime_type, note=None):
        seen["note"] = note
        return []

    async def enrich(items):
        return items

    monkeypatch.setattr(route, "identify_foods", identify)
    monkeypatch.setattr(route, "enrich_detected_foods", enrich)
    img = base64.b64encode(b"\xff\xd8\xffx").decode()
    assert client.post("/estimate-photo", json={"image": img, "note": "  half, with butter "}).status_code == 200
    assert seen["note"] == "half, with butter"
    assert client.post("/estimate-photo", json={"image": img, "note": "x" * 301}).status_code == 422
    seen.clear()
    assert client.post("/estimate-photo", json={"image": img, "note": "   "}).status_code == 200
    assert seen["note"] is None  # a blank note is the old call
