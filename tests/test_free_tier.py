"""Running on Gemini's free tier: one shared daily budget with priorities, a
breaker after a 429, one call per scan, repeat photos remembered, and a cap per
person. Nothing here talks to Google."""

import base64
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.core.config import settings
from app.routers import insights as insights_router
from app.routers import photo_estimation
from app.services import gemini_budget, gemini_client, gemini_service, scan_cache
from app.services.gemini_budget import QuotaExhausted

ME = uuid.UUID("00000000-0000-0000-0000-000000000001")
NOON_PST = datetime(2026, 11, 21, 20, 0, tzinfo=timezone.utc)  # 12:00 in Los Angeles


# ---- the budget -----------------------------------------------------------------------------

def test_without_a_budget_nothing_is_refused(monkeypatch):
    monkeypatch.setattr(settings, "gemini_daily_budget", 0)
    for _ in range(500):
        gemini_budget.record_call(NOON_PST)
    for kind in ("scan", "coach", "insights"):
        gemini_budget.check(kind, NOON_PST)


def test_scans_are_kept_for_last_when_the_budget_runs_low(monkeypatch):
    monkeypatch.setattr(settings, "gemini_daily_budget", 20)
    refused = {}
    for used in range(0, 21):
        for kind in ("insights", "coach", "scan", "estimate"):
            try:
                gemini_budget.check(kind, NOON_PST)
            except QuotaExhausted:
                refused.setdefault(kind, used)
        if used < 20:
            gemini_budget.record_call(NOON_PST)
    # Insights stop after a quarter, the coach after half, scans use everything.
    assert refused == {"insights": 5, "coach": 10, "scan": 20, "estimate": 20}


def test_the_count_starts_again_at_midnight_pacific(monkeypatch):
    monkeypatch.setattr(settings, "gemini_daily_budget", 2)
    gemini_budget.record_call(NOON_PST)
    gemini_budget.record_call(NOON_PST)
    with pytest.raises(QuotaExhausted):
        gemini_budget.check("scan", NOON_PST)
    just_after = datetime(2026, 11, 22, 8, 0, 1, tzinfo=timezone.utc)  # 00:00:01 in Los Angeles (UTC-8)
    gemini_budget.check("scan", just_after)
    assert gemini_budget.used_today(just_after) == 0


def test_the_next_reset_is_midnight_in_los_angeles():
    assert gemini_budget.next_reset(NOON_PST) == datetime(2026, 11, 22, 8, 0, tzinfo=timezone.utc)
    summer = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)  # daylight time, UTC-7
    assert gemini_budget.next_reset(summer) == datetime(2026, 7, 2, 7, 0, tzinfo=timezone.utc)


def test_a_daily_429_blocks_everything_until_the_reset():
    gemini_budget.note_rejected('{"error": {"message": "You exceeded your current quota", "details": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}}', NOON_PST)
    with pytest.raises(QuotaExhausted) as info:
        gemini_budget.check("scan", NOON_PST + timedelta(hours=10))
    assert info.value.daily is True
    gemini_budget.check("scan", datetime(2026, 11, 22, 8, 0, 1, tzinfo=timezone.utc))  # after the reset: allowed


@pytest.mark.parametrize("body, seconds", [
    ('{"retryDelay": "34s"}', 34),
    ('{"retryDelay": "900s"}', gemini_budget.MAX_SHORT_BLOCK_SECONDS),   # never blocks for long on a per-minute limit
    ('You exceeded your current quota, please check your plan', gemini_budget.DEFAULT_SHORT_BLOCK_SECONDS),
    ('', gemini_budget.DEFAULT_SHORT_BLOCK_SECONDS),
])
def test_a_per_minute_429_blocks_only_for_a_short_while(body, seconds):
    gemini_budget.note_rejected(body, NOON_PST)
    with pytest.raises(QuotaExhausted) as info:
        gemini_budget.check("scan", NOON_PST + timedelta(seconds=seconds - 1))
    assert info.value.daily is False
    gemini_budget.check("scan", NOON_PST + timedelta(seconds=seconds + 1))


def test_what_counts_as_a_quota_error():
    request = httpx.Request("POST", "https://gemini.test")
    assert gemini_budget.is_quota_error(QuotaExhausted())
    assert gemini_budget.is_quota_error(httpx.HTTPStatusError("x", request=request, response=httpx.Response(429, request=request)))
    assert not gemini_budget.is_quota_error(httpx.HTTPStatusError("x", request=request, response=httpx.Response(500, request=request)))
    assert not gemini_budget.is_quota_error(RuntimeError("boom"))


# ---- the client ------------------------------------------------------------------------------------

class _Resp:
    def __init__(self, status, payload=None, text=""):
        self.status_code, self._payload, self.text = status, payload, text
        self.request = httpx.Request("POST", "https://gemini.test")

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("upstream", request=self.request, response=self)


class _Http:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, *a, **k):
        self.calls += 1
        return self.responses.pop(0)


def _http(monkeypatch, *responses):
    fake = _Http(*responses)
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: fake)
    return fake


async def test_after_a_429_no_further_call_is_even_sent(monkeypatch):
    http = _http(monkeypatch, _Resp(429, text='{"error": "quota", "retryDelay": "30s"}'))
    with pytest.raises(httpx.HTTPStatusError):
        await gemini_client.generate_content({"contents": []}, kind="coach")
    assert http.calls == 1
    for kind in ("scan", "coach", "insights"):
        with pytest.raises(QuotaExhausted):
            await gemini_client.generate_content({"contents": []}, kind=kind)
    assert http.calls == 1  # nothing was sent to Google while it is refusing


async def test_answered_calls_are_counted_against_the_budget(monkeypatch):
    monkeypatch.setattr(settings, "gemini_daily_budget", 2)
    ok = {"candidates": []}
    http = _http(monkeypatch, _Resp(200, ok), _Resp(200, ok), _Resp(200, ok))
    await gemini_client.generate_content({"contents": []}, kind="scan")
    await gemini_client.generate_content({"contents": []}, kind="scan")
    with pytest.raises(QuotaExhausted):
        await gemini_client.generate_content({"contents": []}, kind="scan")
    assert http.calls == 2


# ---- the scan: one call, per-item breakdown ---------------------------------------------------------

def _scan_route(client, monkeypatch, detected, usda=None, estimate_result=None, image=b"\xff\xd8\xffone", note=None, region=None, raises=None):
    seen = {"identify": 0, "estimate": 0}

    async def identify(image_bytes, mime_type, **kw):
        seen["identify"] += 1
        if raises is not None:
            raise raises
        return [dict(d) for d in detected]

    async def enrich(items):
        return [{**i, "matched": False, "matched_description": None, "matched_fdc_id": None,
                 "calories_per_100g": None, "protein_g_per_100g": None, "carbs_g_per_100g": None,
                 "fat_g_per_100g": None, **(usda or {}).get(i["name"], {})} for i in items]

    async def estimate(names, region=None, **kw):
        seen["estimate"] += 1
        seen["estimate_names"] = names
        return estimate_result or {}

    monkeypatch.setattr(photo_estimation, "identify_foods", identify)
    monkeypatch.setattr(photo_estimation, "enrich_detected_foods", enrich)
    monkeypatch.setattr(photo_estimation, "estimate_foods", estimate)
    body = {"image": base64.b64encode(image).decode()}
    if note:
        body["note"] = note
    if region:
        body["region"] = region
    return client.post("/estimate-photo", json=body), seen


GOOD = {"calories_per_100g": 165, "protein_g": 31.0, "carbs_g": 0.0, "fat_g": 3.6, "basis": "typical grilled chicken breast"}
RICE = {"calories_per_100g": 130, "protein_g": 2.7, "carbs_g": 28.0, "fat_g": 0.3, "basis": "plain boiled white rice"}


def test_each_ingredient_gets_its_calories_from_the_one_scan_call_when_the_database_has_nothing(client, monkeypatch):
    """The reported problem: the database is unavailable and the second call is rate limited, yet
    every ingredient on the plate still comes back with calories."""
    r, seen = _scan_route(client, monkeypatch, [
        {"name": "grilled chicken", "estimated_grams": 150.0, "estimate": GOOD},
        {"name": "white rice", "estimated_grams": 200.0, "estimate": RICE},
    ])
    assert r.status_code == 200 and seen["estimate"] == 0  # no second Gemini call
    chicken, rice = r.json()
    assert (chicken["name"], chicken["calories_per_100g"], chicken["source"]) == ("grilled chicken", 165, "ai_estimate")
    assert (rice["name"], rice["calories_per_100g"], rice["confidence"]) == ("white rice", 130, "medium")
    assert chicken["estimate_basis"] == "typical grilled chicken breast"
    assert "estimate" not in chicken  # the raw model object never reaches the app


def test_a_database_match_wins_over_the_scans_own_estimate(client, monkeypatch):
    usda = {"white rice": {"matched": True, "calories_per_100g": 128.0, "protein_g_per_100g": 2.4, "carbs_g_per_100g": 28.0, "fat_g_per_100g": 0.2}}
    r, seen = _scan_route(client, monkeypatch, [{"name": "white rice", "estimated_grams": 200.0, "estimate": RICE}], usda=usda)
    item = r.json()[0]
    assert item["calories_per_100g"] == 128 and item["source"] == "usda" and item["confidence"] == "high"
    assert item["estimate_basis"] is None and seen["estimate"] == 0


def test_an_absurd_inline_estimate_is_dropped_and_only_that_item_is_asked_about_again(client, monkeypatch):
    absurd = {"calories_per_100g": 5000, "protein_g": 90.0, "carbs_g": 90.0, "fat_g": 90.0, "basis": "nonsense"}
    again = {"stew": {"calories_per_100g": 100.0, "protein_g_per_100g": 5.0, "carbs_g_per_100g": 10.0, "fat_g_per_100g": 4.0, "basis": "typical stew"}}
    r, seen = _scan_route(client, monkeypatch, [
        {"name": "stew", "estimated_grams": 250.0, "estimate": absurd},
        {"name": "white rice", "estimated_grams": 200.0, "estimate": RICE},
    ], estimate_result=again)
    assert seen["estimate"] == 1 and seen["estimate_names"] == ["stew"]
    stew, rice = r.json()
    assert stew["source"] == "ai_estimate" and stew["calories_per_100g"] == 100.0 and rice["calories_per_100g"] == 130


def test_an_item_with_no_estimate_at_all_stays_unmatched_when_the_fallback_also_fails(client, monkeypatch):
    r, seen = _scan_route(client, monkeypatch, [{"name": "mystery", "estimated_grams": 100.0}])
    item = r.json()[0]
    assert r.status_code == 200 and item["matched"] is False and item["calories_per_100g"] is None


def test_the_scan_prompt_asks_for_each_ingredient_apart_with_its_numbers():
    prompt = gemini_service.PROMPT
    for must in ("each as its own item", "Break a mixed plate apart", 'never one item such as "plate of food"', "per 100 grams", '"estimate"'):
        assert must in prompt
    schema = gemini_service._API_ERRORS["response_json_schema"]["items"]["properties"]
    assert set(schema["estimate"]["properties"]) == {"calories_per_100g", "protein_g", "carbs_g", "fat_g", "basis"}


def test_the_estimate_in_a_reply_is_kept_raw_for_the_checks_and_ignored_when_it_is_not_an_object():
    import json

    def reply(items):
        return {"candidates": [{"content": {"parts": [{"text": json.dumps(items)}]}}]}

    items = gemini_service._extract_items(reply([
        {"name": "rice", "estimated_grams": 100, "estimate": RICE},
        {"name": "bread", "estimated_grams": 50, "estimate": "about 250 kcal"},
    ]))
    assert items[0]["estimate"] == RICE and "estimate" not in items[1]


# ---- the scan: quota, repeats, and the cap per person --------------------------------------------------

def test_a_spent_quota_is_a_distinct_answer_the_app_does_not_retry(client, monkeypatch):
    r, _ = _scan_route(client, monkeypatch, [], raises=QuotaExhausted(daily=True))
    assert r.status_code == 429 and r.json()["detail"] == "ai_quota"
    request = httpx.Request("POST", "https://gemini.test")
    google = httpx.HTTPStatusError("x", request=request, response=httpx.Response(429, request=request))
    r, _ = _scan_route(client, monkeypatch, [], raises=google, image=b"\xff\xd8\xfftwo")
    assert r.status_code == 429 and r.json()["detail"] == "ai_quota"


def test_any_other_failure_is_still_a_502(client, monkeypatch):
    r, _ = _scan_route(client, monkeypatch, [], raises=RuntimeError("boom"))
    assert r.status_code == 502


def test_the_same_photo_is_asked_about_once_and_counted_once(client, monkeypatch, usage_db):
    detected = [{"name": "white rice", "estimated_grams": 200.0, "estimate": RICE}]
    first, seen = _scan_route(client, monkeypatch, detected)
    again, seen2 = _scan_route(client, monkeypatch, detected)
    assert first.json() == again.json() and seen["identify"] == 1 and seen2["identify"] == 0
    assert len(usage_db.statements) == 1  # the repeat cost nothing, so it is not counted either


def test_a_different_note_region_or_photo_is_a_new_question(client, monkeypatch):
    detected = [{"name": "white rice", "estimated_grams": 200.0, "estimate": RICE}]
    asked = 0
    for kwargs in ({}, {"note": "half of this"}, {"region": "west_africa"}, {"image": b"\xff\xd8\xffother"}):
        _, seen = _scan_route(client, monkeypatch, detected, **kwargs)
        asked += seen["identify"]
    assert asked == 4


def test_the_daily_cap_counts_only_successful_scans_and_stops_the_extra_one(client, monkeypatch):
    monkeypatch.setattr(settings, "scans_per_user_per_day", 2)
    detected = [{"name": "white rice", "estimated_grams": 200.0, "estimate": RICE}]
    failed, _ = _scan_route(client, monkeypatch, detected, raises=RuntimeError("boom"), image=b"\xff\xd8\xffa")
    quota, _ = _scan_route(client, monkeypatch, detected, raises=QuotaExhausted(), image=b"\xff\xd8\xffb")
    assert (failed.status_code, quota.status_code) == (502, 429)  # neither used up the day
    assert _scan_route(client, monkeypatch, detected, image=b"\xff\xd8\xffc")[0].status_code == 200
    repeat = _scan_route(client, monkeypatch, detected, image=b"\xff\xd8\xffc")[0]
    assert repeat.status_code == 200  # a repeat is free
    assert _scan_route(client, monkeypatch, detected, image=b"\xff\xd8\xffd")[0].status_code == 200
    over = _scan_route(client, monkeypatch, detected, image=b"\xff\xd8\xffe")[0]
    assert over.status_code == 429 and over.json()["detail"] == "daily_scan_cap"


def test_with_no_cap_set_nobody_is_limited_by_it(client, monkeypatch):
    monkeypatch.setattr(settings, "scans_per_user_per_day", 0)
    detected = [{"name": "white rice", "estimated_grams": 200.0, "estimate": RICE}]
    for n in range(5):
        assert _scan_route(client, monkeypatch, detected, image=b"\xff\xd8\xff" + bytes([n]))[0].status_code == 200


def test_the_scan_cache_forgets_after_an_hour_and_keeps_no_photo():
    key = scan_cache.key_for(b"photo-bytes", "n", "r", "en")
    assert key != scan_cache.key_for(b"photo-bytes", "n", "r", "es") and b"photo-bytes".hex() not in key
    scan_cache.put(key, [{"name": "rice"}], now=1000.0)
    assert scan_cache.get(key, now=1000.0 + scan_cache.TTL_SECONDS - 1) == [{"name": "rice"}]
    assert scan_cache.get(key, now=1000.0 + scan_cache.TTL_SECONDS + 1) is None
    got = scan_cache.get(scan_cache.key_for(b"x", None, None, "en"))
    assert got is None
    scan_cache.put("a", [{"name": "x"}], now=1.0)
    scan_cache.get("a", now=2.0)[0]["name"] = "changed"
    assert scan_cache.get("a", now=2.0) == [{"name": "x"}]  # callers cannot change what is remembered


# ---- Insights and the coach ---------------------------------------------------------------------------

class _NoCache:
    def scalar_one_or_none(self):
        return None


class _Db:
    async def execute(self, stmt):
        return _NoCache()

    async def commit(self):
        pass

    async def rollback(self):
        pass


def _insights_stubs(monkeypatch):
    called = []

    async def trend(db, user_id, today):
        return [{"date": "2026-11-21", "calories": 0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0}]

    async def generate(db, user_id, trend_, today, lang="en"):
        called.append(1)
        return {"narrative": "from the model", "tips": ["a"], "weekly_trend": trend_}

    monkeypatch.setattr(insights_router, "get_weekly_trend", trend)
    monkeypatch.setattr(insights_router, "generate_insights", generate)
    return called


async def test_with_the_narrative_switched_off_insights_make_no_gemini_call(monkeypatch):
    called = _insights_stubs(monkeypatch)
    monkeypatch.setattr(settings, "gemini_insights", False)
    out = await insights_router.get_insights(user_id=uuid.uuid4(), db=_Db(), lang="en")
    assert called == [] and out.narrative and out.narrative != "from the model" and out.weekly_trend


async def test_with_it_switched_on_the_narrative_is_generated(monkeypatch):
    called = _insights_stubs(monkeypatch)
    monkeypatch.setattr(settings, "gemini_insights", True)
    out = await insights_router.get_insights(user_id=uuid.uuid4(), db=_Db(), lang="en")
    assert called == [1] and out.narrative == "from the model"


async def test_a_spent_quota_gives_insights_the_plain_answer_not_an_error(monkeypatch):
    _insights_stubs(monkeypatch)

    async def refused(db, user_id, trend_, today, lang="en"):
        raise QuotaExhausted(daily=True)

    monkeypatch.setattr(insights_router, "generate_insights", refused)
    out = await insights_router.get_insights(user_id=uuid.uuid4(), db=_Db(), lang="en")
    assert out.narrative and out.weekly_trend


# ---- a second model when the first one's day is spent -----------------------------------------------------

class _ByModel:
    """Fake HTTP that answers per model, taken from the URL."""

    def __init__(self, answers):
        self.answers, self.urls = answers, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, **kw):
        self.urls.append(url)
        model = url.split("/models/")[1].split(":")[0]
        return self.answers[model]


DAILY_429 = '{"error": {"details": [{"violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}]}}'


def _by_model(monkeypatch, answers, fallback="backup-model", main="main-model"):
    monkeypatch.setattr(settings, "gemini_model", main)
    monkeypatch.setattr(settings, "gemini_fallback_model", fallback)
    fake = _ByModel(answers)
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: fake)
    return fake


async def test_a_429_on_the_main_model_moves_the_same_request_to_the_fallback(monkeypatch):
    fake = _by_model(monkeypatch, {"main-model": _Resp(429, text=DAILY_429), "backup-model": _Resp(200, {"candidates": ["ok"]})})
    data = await gemini_client.generate_content({"contents": []}, kind="scan")
    assert data == {"candidates": ["ok"]}
    assert [u.split("/models/")[1].split(":")[0] for u in fake.urls] == ["main-model", "backup-model"]


async def test_once_the_main_model_is_spent_it_is_not_called_again_until_the_reset(monkeypatch):
    fake = _by_model(monkeypatch, {"main-model": _Resp(429, text=DAILY_429), "backup-model": _Resp(200, {"candidates": []})})
    for _ in range(3):
        await gemini_client.generate_content({"contents": []}, kind="scan")
    called = [u.split("/models/")[1].split(":")[0] for u in fake.urls]
    assert called == ["main-model", "backup-model", "backup-model", "backup-model"]  # the main one is tried once only


async def test_with_both_models_spent_the_caller_gets_the_quota_error(monkeypatch):
    _by_model(monkeypatch, {"main-model": _Resp(429, text=DAILY_429), "backup-model": _Resp(429, text=DAILY_429)})
    with pytest.raises(httpx.HTTPStatusError) as info:
        await gemini_client.generate_content({"contents": []}, kind="scan")
    assert gemini_budget.is_quota_error(info.value)


async def test_without_a_fallback_nothing_changes(monkeypatch):
    fake = _by_model(monkeypatch, {"main-model": _Resp(429, text=DAILY_429)}, fallback="")
    with pytest.raises(httpx.HTTPStatusError):
        await gemini_client.generate_content({"contents": []}, kind="scan")
    assert len(fake.urls) == 1


async def test_other_errors_do_not_trigger_the_fallback(monkeypatch):
    fake = _by_model(monkeypatch, {"main-model": _Resp(400, text="bad request"), "backup-model": _Resp(200, {"candidates": []})})
    with pytest.raises(httpx.HTTPStatusError):
        await gemini_client.generate_content({"contents": []}, kind="scan")
    assert len(fake.urls) == 1


async def test_each_model_has_its_own_budget_and_the_fallback_its_own_number(monkeypatch):
    monkeypatch.setattr(settings, "gemini_daily_budget", 1)
    monkeypatch.setattr(settings, "gemini_fallback_daily_budget", 2)
    ok = _Resp(200, {"candidates": []})
    fake = _by_model(monkeypatch, {"main-model": ok, "backup-model": ok})
    for _ in range(3):
        await gemini_client.generate_content({"contents": []}, kind="scan")
    called = [u.split("/models/")[1].split(":")[0] for u in fake.urls]
    assert called == ["main-model", "backup-model", "backup-model"]  # 1 on the main, then 2 on the backup
    with pytest.raises(QuotaExhausted):
        await gemini_client.generate_content({"contents": []}, kind="scan")
    assert gemini_budget.used_today(model="main-model") == 1 and gemini_budget.used_today(model="backup-model") == 2
