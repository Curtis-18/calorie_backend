"""What the Insights model is told: whole grams and natural day names, never
raw sums of floats or ISO dates (the AI coach paragraph once said
"43.090999999999994g" and "2026-11-18")."""

import json
import re
from datetime import date
from types import SimpleNamespace

import pytest

from app.i18n import SUPPORTED
from app.i18n.dates import day_label
from app.services import insights_service

TODAY = date(2026, 11, 18)  # a Wednesday


class _Result:
    def scalar_one_or_none(self):
        return SimpleNamespace(calorie_target=1941, protein_g=120, carbs_g=200, fat_g=60)


class _Db:
    async def execute(self, *_a, **_k):
        return _Result()


def _trend():
    return [
        {"date": "2026-11-17", "calories": 1500, "protein_g": 43.090999999999994, "carbs_g": 150.04999999999998, "fat_g": 50.5},
        {"date": "2026-11-18", "calories": 900, "protein_g": 43.090999999999994, "carbs_g": 80.49, "fat_g": 20.2},
    ]


async def _prompt(monkeypatch, lang="en", trend=None):
    seen = {}

    async def fake(payload, kind=None):
        seen["prompt"] = payload["contents"][0]["parts"][0]["text"]
        return {"candidates": [{"content": {"parts": [{"text": json.dumps({"narrative": "ok", "tips": []})}]}}]}

    monkeypatch.setattr(insights_service, "generate_content", fake)
    await insights_service.generate_insights(_Db(), "u1", trend or _trend(), TODAY, lang)
    return seen["prompt"]


@pytest.mark.asyncio
async def test_amounts_are_whole_numbers_never_long_floats(monkeypatch):
    prompt = await _prompt(monkeypatch)
    assert "43g protein" in prompt and "150g carbs" in prompt and "80g carbs" in prompt
    assert not re.search(r"\d\.\d{2,}", prompt), prompt
    assert "Today so far: 900 kcal, 43g protein, 80g carbs, 20g fat." in prompt


@pytest.mark.asyncio
async def test_days_read_naturally_not_as_iso_dates(monkeypatch):
    prompt = await _prompt(monkeypatch)
    assert "Tue 17 Nov: 1500 kcal" in prompt and "Wed 18 Nov: 900 kcal" in prompt
    assert "2026-11" not in prompt


@pytest.mark.asyncio
async def test_days_follow_the_persons_language(monkeypatch):
    prompt = await _prompt(monkeypatch, lang="de")
    assert "Mi 18 Nov" in prompt and "Di 17 Nov" in prompt
    assert "2026-11" not in prompt


@pytest.mark.asyncio
async def test_missing_amounts_read_as_zero_and_a_bad_date_does_not_crash(monkeypatch):
    prompt = await _prompt(monkeypatch, trend=[{"date": "not-a-date", "calories": 0, "protein_g": None, "carbs_g": 0, "fat_g": 0}])
    assert "not-a-date: 0 kcal, 0g protein" in prompt
    assert "Today so far: 0 kcal, 0g protein, 0g carbs, 0g fat." in prompt


def test_day_label_in_every_language():
    assert day_label(TODAY, "en") == "Wed 18 Nov"
    assert day_label(date(2026, 3, 1), "en") == "Sun 1 Mar"
    for lang in SUPPORTED:
        label = day_label(TODAY, lang)
        assert re.fullmatch(r"\S+ 18 \S+", label), (lang, label)
    assert day_label(TODAY, "xx") == "Wed 18 Nov"  # unknown language: English
    assert day_label(TODAY, "es") == "mié 18 nov" and day_label(TODAY, "fr") == "mer 18 nov"


@pytest.mark.asyncio
async def test_the_model_is_no_longer_asked_for_tips_and_the_answer_has_an_empty_tips_key(monkeypatch):
    prompt = await _prompt(monkeypatch)
    assert "tips" not in prompt.lower()
    assert '"narrative"' in prompt

    async def fake(payload, kind=None):
        # A model that still sends tips (an old cached prompt, say): they are dropped.
        return {"candidates": [{"content": {"parts": [{"text": json.dumps({"narrative": "ok", "tips": ["a", "b"]})}]}}]}

    monkeypatch.setattr(insights_service, "generate_content", fake)
    out = await insights_service.generate_insights(_Db(), "u1", _trend(), TODAY, "en")
    assert out["tips"] == [] and out["narrative"] == "ok"


def test_the_degraded_answer_says_summary_not_tips_in_every_language():
    from app.i18n import SUPPORTED

    for lang in SUPPORTED:
        out = insights_service.degraded_insights([], lang)
        assert out["tips"] == []
        if lang == "en":
            assert "tips" not in out["narrative"].lower() and "summary" in out["narrative"]


# ---- movement (Workouts tab) ------------------------------------------------------------------

def test_the_prompt_is_unchanged_when_there_is_no_movement():
    import asyncio

    seen = {}

    async def fake_generate(payload, kind=None):
        seen["prompt"] = payload["contents"][0]["parts"][0]["text"]
        return {"candidates": [{"content": {"parts": [{"text": '{"narrative": "ok"}'}]}}]}

    from datetime import date
    from unittest.mock import patch

    from app.services import insights_service

    trend = [{"date": "2026-11-25", "calories": 1000, "protein_g": 50, "carbs_g": 100, "fat_g": 30}]
    with patch.object(insights_service, "generate_content", fake_generate):
        asyncio.run(insights_service.generate_insights(_Db(), "u", trend, date(2026, 11, 25), "en"))
        without = seen["prompt"]
        asyncio.run(insights_service.generate_insights(_Db(), "u", trend, date(2026, 11, 25), "en", {"week_minutes": 0, "active_days": 0}))
        assert seen["prompt"] == without
        asyncio.run(insights_service.generate_insights(_Db(), "u", trend, date(2026, 11, 25), "en", {"week_minutes": 95, "active_days": 3}))
        with_move = seen["prompt"]
    assert "Movement" not in without
    assert "95 min on 3 day(s)" in with_move
    assert "never suggest eating more or less" in with_move
    assert "never say it burns or earns anything" in with_move
