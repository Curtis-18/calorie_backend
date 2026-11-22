"""What the server writes (report, badges, insights, extras, budget, push, scan
names) in the languages the app offers."""

import base64
import re
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from app.i18n import DEFAULT, LANGUAGE_NAMES, SUPPORTED, TABLES, normalize, parse_language, t

OTHER = [c for c in SUPPORTED if c != "en"]
HOLES = re.compile(r"\{(\w+)\}")


# ---- the tables ---------------------------------------------------------------------

def test_every_language_has_the_same_phrases_with_the_same_placeholders():
    reference = TABLES["es"]
    for code in OTHER:
        assert set(TABLES[code]) == set(reference), code
        for english, text in TABLES[code].items():
            assert text.strip(), (code, english)
            assert set(HOLES.findall(text)) == set(HOLES.findall(english)), (code, english)
    assert set(TABLES) == set(OTHER) and set(LANGUAGE_NAMES) == set(SUPPORTED)


def test_every_literal_passed_to_t_has_a_translation():
    """Catches a typo in a phrase, which would silently stay English."""
    call = re.compile(r"""\bt\(\s*(?:lang|language)\s*,\s*(?:"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)')""", re.S)
    missing = []
    for path in Path("app").rglob("*.py"):
        if "i18n" in path.parts:
            continue
        text = path.read_text()
        # Adjacent string literals are one phrase.
        text = re.sub(r'"\s*\n\s*"', "", text)
        for m in call.finditer(text):
            phrase = (m.group(1) if m.group(1) is not None else m.group(2)).replace("\\'", "'").replace('\\"', '"')
            if phrase not in TABLES["es"]:
                missing.append((str(path), phrase[:60]))
    assert not missing


def test_the_data_tables_are_covered():
    from app.services.adjustments import EXTRAS
    from app.services.insights_service import FALLBACK_NARRATIVE
    from app.services.notification_rules import _COPY
    from app.services.progress_service import ACHIEVEMENTS

    phrases = {FALLBACK_NARRATIVE, "Restaurant portion"}
    phrases |= {a.title for a in ACHIEVEMENTS} | {a.description for a in ACHIEVEMENTS}
    phrases |= {e.label for e in EXTRAS} | {e.entry_name for e in EXTRAS}
    for options in _COPY.values():
        for title, body in options:
            phrases |= {title, body}
    assert [p for p in phrases if p not in TABLES["es"]] == []


# ---- choosing the language -------------------------------------------------------------

def test_accept_language_picks_the_best_supported_language():
    assert parse_language("es-MX,es;q=0.9,en;q=0.8") == "es"
    assert parse_language("pt-BR") == "pt"
    assert parse_language("ja,ko;q=0.5") == "en"
    assert parse_language("xx, fr;q=0.5") == "fr"
    assert parse_language("de;q=0.2, it;q=0.9") == "it"
    assert parse_language("") == parse_language(None) == DEFAULT
    assert parse_language("*;q=0.5, ;;;, es;q=abc") == "en"  # junk is ignored, never an error


def test_t_falls_back_to_english_and_fills_placeholders():
    assert t("es", "Never translated {n}", n=3) == "Never translated 3"
    assert t("xx", "Log your first meal.") == "Log your first meal."
    assert t("de", "Your {count}-day flame is safe.", count=4) == "Deine 4-Tage-Flamme ist sicher."
    assert normalize("ES-mx") == "es" and normalize("zz") == "en" and normalize(None) == "en"


# ---- the weekly report --------------------------------------------------------------------

def _days(n):
    from app.services.patterns import Entry

    out = []
    for i in range(n):
        d = date(2026, 11, 1 + i)
        out.append(Entry(d, datetime(d.year, d.month, d.day, 21, 0), "lunch", 600, 10))
        out.append(Entry(d, datetime(d.year, d.month, d.day, 21, 30), "dinner", 900, 30))
    return out


def test_the_report_is_written_in_the_requested_language():
    from app.services.patterns import build_report

    today = date(2026, 11, 20)
    english = build_report(_days(18), today, 100)
    spanish = build_report(_days(18), today, 100, lang="es")
    assert english["patterns"] and len(english["patterns"]) == len(spanish["patterns"])
    assert [p["id"] for p in english["patterns"]] == [p["id"] for p in spanish["patterns"]]
    assert english["message"].startswith("You logged") and spanish["message"].startswith("Registraste")
    for p in spanish["patterns"]:
        assert p["text"] and p["tip"] and "{" not in p["text"] + p["tip"]
    assert any(p["text"] not in {e["text"] for e in english["patterns"]} for p in spanish["patterns"])


def test_every_summary_line_translates():
    from app.services.patterns import summary_message

    for n in (0, 3, 6):
        for code in OTHER:
            assert summary_message(n, code) != summary_message(n)


def test_the_report_route_reads_the_header(client, monkeypatch):
    from app.routers import reports

    seen = {}
    real = reports.build_report

    def spy(entries, today, protein, fiber, lang="en"):
        seen["lang"] = lang
        return real(entries, today, protein, fiber, lang)

    class _Rows:
        def all(self):
            return []

        def one_or_none(self):
            return None

    class _Db:
        async def execute(self, stmt):
            return _Rows()

    from app.core.database import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: _Db()
    monkeypatch.setattr(reports, "build_report", spy)
    # The route only accepts a device date within a day of the server's UTC date,
    # so a fixed date here would start failing as soon as the calendar moved on.
    from datetime import datetime, timezone

    day = datetime.now(timezone.utc).date().isoformat()
    body = client.get("/reports/weekly", params={"date": day}, headers={"Accept-Language": "fr-CA,fr;q=0.9"}).json()
    assert seen["lang"] == "fr" and body["message"].startswith("Une nouvelle semaine")
    assert client.get("/reports/weekly", params={"date": day}).json()["message"].startswith("A fresh week")


# ---- badges ---------------------------------------------------------------------------------

def test_badges_are_translated_and_the_hour_is_filled_in():
    from app.services.progress_service import compute_progress

    en = compute_progress([], date(2026, 11, 20), None, None)
    it = compute_progress([], date(2026, 11, 20), None, None, lang="it")
    by_id = {a["id"]: a for a in it["achievements"]}
    assert [a["id"] for a in en["achievements"]] == list(by_id)
    assert by_id["first_bite"]["title"] == "Primo morso"
    assert by_id["early_bird"]["description"] == "Registra la colazione prima delle 9."
    english = {a["id"]: a for a in en["achievements"]}
    assert english["early_bird"]["description"] == "Log breakfast before 9 am."
    for code in OTHER:
        out = compute_progress([], date(2026, 11, 20), None, None, lang=code)
        assert all("{" not in a["title"] + a["description"] for a in out["achievements"])


# ---- the weekly budget -------------------------------------------------------------------------

def test_the_budget_nudge_and_explanation_are_translated():
    from app.routers.budget import _explain
    from app.services.week_budget import compute_nudge

    kwargs = dict(shown_allowance=2000, eaten_today=2300, days_left_after_today=3, target=2000, floor=1400, goal="lose")
    en = compute_nudge(**kwargs)
    de = compute_nudge(**kwargs, lang="de")
    assert en.message.startswith("You're about") and de.message.startswith("Du liegst heute etwa")
    assert str(en.per_day) in de.message and "3 Tage" in de.message
    one = compute_nudge(**{**kwargs, "days_left_after_today": 1}, lang="pt")
    assert "próximo dia" in one.message
    for code in OTHER:
        for bank in (0, -100, 100):
            assert _explain(bank, True, code) != _explain(bank, True)
        assert _explain(0, False, code) != _explain(0, False)


# ---- one-tap extras --------------------------------------------------------------------------------

def test_the_extras_route_words_each_chip_in_the_language(client, monkeypatch):
    from app.routers import adjustments

    async def fake():
        return [
            {"id": "oil", "kind": "add", "label": "+ Cooking oil", "entry_name": "Cooking oil, 1 tbsp (added)", "grams": 14},
            {"id": "restaurant", "kind": "scale", "label": "Restaurant portion", "factor": 1.25},
        ]

    monkeypatch.setattr(adjustments, "list_adjustments", fake)
    es = client.get("/adjustments", headers={"Accept-Language": "es"}).json()
    assert es[0]["label"] == "+ Aceite de cocina" and es[0]["entry_name"].startswith("Aceite de cocina")
    assert es[1]["label"] == "Ración de restaurante" and "entry_name" not in es[1]
    assert client.get("/adjustments").json()[0]["label"] == "+ Cooking oil"


# ---- push notifications --------------------------------------------------------------------------------

def test_every_push_kind_reads_in_every_language_with_the_values_filled_in():
    from app.services.notification_rules import Kind, copy_for

    for kind in Kind:
        for key in ("a", "b", "c", "d", "e"):
            for lang in SUPPORTED:
                title, body = copy_for(kind, key, lang, name="sam", emoji="🔥", count=6)
                assert title and body and "{" not in title + body, (kind, lang)


def test_the_push_wording_follows_the_language_and_stays_stable_per_event():
    from app.services.notification_rules import Kind, copy_for

    en = copy_for(Kind.FRIEND_SNAP, "snap:1", "en", name="sam")
    fr = copy_for(Kind.FRIEND_SNAP, "snap:1", "fr", name="sam")
    assert fr != en and fr == copy_for(Kind.FRIEND_SNAP, "snap:1", "fr", name="sam")
    assert "sam" in fr[0]


class _Savepoint:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _LangDb:
    def __init__(self, stored=None, fail=False):
        self.stored, self.fail, self.saved = stored, fail, None

    def begin_nested(self):
        return _Savepoint()

    async def execute(self, stmt):
        if self.fail:
            raise RuntimeError('relation "user_language" does not exist')
        if str(stmt).lstrip().upper().startswith("INSERT"):
            self.saved = stmt.compile().params
            return None

        class R:
            def __init__(self, v):
                self.v = v

            def scalar_one_or_none(self):
                return self.v

        return R(self.stored)

    async def commit(self):
        pass


async def test_the_remembered_language_is_read_and_a_missing_table_means_english():
    from app.services import language_pref

    me = uuid.uuid4()
    assert await language_pref.recall(_LangDb("es"), me) == "es"
    assert await language_pref.recall(_LangDb(None), me) == "en"
    assert await language_pref.recall(_LangDb("klingon"), me) == "en"
    assert await language_pref.recall(_LangDb(fail=True), me) == "en"
    db = _LangDb()
    assert await language_pref.remember(db, me, "PT-br") is True and db.saved["language"] == "pt"
    assert await language_pref.remember(_LangDb(fail=True), me, "es") is False


def test_the_language_endpoint_saves_it_and_refuses_unknown_ones(client):
    from app.core.database import get_db
    from app.main import app

    db = _LangDb()
    app.dependency_overrides[get_db] = lambda: db
    assert client.post("/prefs/language", json={"language": "de"}).status_code == 204
    assert db.saved["language"] == "de"
    assert client.post("/prefs/language", json={"language": "tlh"}).status_code == 422
    # Before the migration it is a quiet no-op, never an error in the app.
    app.dependency_overrides[get_db] = lambda: _LangDb(fail=True)
    assert client.post("/prefs/language", json={"language": "de"}).status_code == 204


async def test_notify_writes_the_push_in_the_recipients_language(monkeypatch):
    from app.services import notifier
    from app.services.notification_rules import Kind

    me = uuid.uuid4()
    sent = {}

    class R:
        def __init__(self, rows=None, one=None, scalar=0):
            self.rows, self.one, self.scalar = rows or [], one, scalar

        def scalars(self):
            return self

        def all(self):
            return self.rows

        def scalar_one_or_none(self):
            return self.one

        def scalar_one(self):
            return self.scalar

    class Db:
        def __init__(self):
            self.n = 0

        def begin_nested(self):
            return _Savepoint()

        async def execute(self, stmt):
            text = str(stmt)
            if "device_tokens" in text and text.lstrip().upper().startswith("SELECT"):
                return R(rows=["tok"])
            if "user_language" in text:
                return R(one="es")
            if "count(" in text:
                return R(scalar=0)
            if text.lstrip().upper().startswith("INSERT"):
                sent["row"] = stmt.compile().params
                return R(one=uuid.uuid4())
            return R()

        async def commit(self):
            pass

    async def fake_send(tokens, title, body, data):
        sent["title"], sent["body"] = title, body
        return "sent"

    monkeypatch.setattr(notifier.push_sender, "send", fake_send)
    status = await notifier.notify(Db(), me, Kind.FRIEND_SNAP, dedupe_key="snap:9", name="sam", now=datetime(2026, 11, 20, 13, 0, tzinfo=timezone.utc))
    assert status == "sent" and "sam" in sent["title"]
    assert sent["title"] != "🍜 sam sent you a bite" and sent["title"].count("sam") == 1


# ---- insights ---------------------------------------------------------------------------------------------

async def test_the_insights_prompt_asks_for_the_language_only_when_it_is_not_english(monkeypatch):
    from app.services import insights_service

    prompts = []

    async def fake_generate(payload, kind=None):
        prompts.append(payload["contents"][0]["parts"][0]["text"])
        return {"candidates": [{"content": {"parts": [{"text": '{"narrative": "n"}'}]}}]}

    monkeypatch.setattr(insights_service, "generate_content", fake_generate)

    class Db:
        async def execute(self, stmt):
            class R:
                def scalar_one_or_none(self):
                    return None

            return R()

    trend = [{"date": "2026-11-20", "calories": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0}]
    en = await insights_service.generate_insights(Db(), "u", trend, date(2026, 11, 20))
    es = await insights_service.generate_insights(Db(), "u", trend, date(2026, 11, 20), "es")
    assert "Write the narrative" not in prompts[0] and "in Spanish" in prompts[1]
    assert en["language"] == "en" and es["language"] == "es"


def test_the_degraded_insights_are_translated():
    from app.services.insights_service import degraded_insights

    en, fr = degraded_insights([]), degraded_insights([], "fr")
    assert fr["narrative"] != en["narrative"]
    assert fr["tips"] == en["tips"] == []  # tips were removed; the key stays empty for older copies of the app


async def test_a_cached_narrative_in_another_language_is_not_served(monkeypatch):
    from datetime import timedelta

    from app.routers import insights as router

    trend = [{"date": "2026-11-20", "calories": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0}]
    calls = []

    async def fake_trend(db, user_id, today):
        return trend

    async def fake_generate(db, user_id, t_, today, lang="en"):
        calls.append(lang)
        return {"narrative": "nuevo", "tips": [], "weekly_trend": t_, "language": lang}

    monkeypatch.setattr(router, "get_weekly_trend", fake_trend)
    monkeypatch.setattr(router, "generate_insights", fake_generate)
    router.insight_generations.reset()

    class Cached:
        date = datetime.now(timezone.utc).date()
        payload = {"narrative": "old english", "tips": [], "weekly_trend": trend}  # no marker = English
        generated_at = router._utcnow_naive() - timedelta(minutes=5)

    class Db:
        async def execute(self, stmt):
            class R:
                def scalar_one_or_none(self):
                    return Cached()

            return R()

        async def commit(self):
            pass

        async def rollback(self):
            pass

    out = await router.get_insights(refresh=False, user_id=uuid.uuid4(), db=Db(), lang="es")
    assert calls == ["es"] and out.narrative == "nuevo"
    out = await router.get_insights(refresh=False, user_id=uuid.uuid4(), db=Db(), lang="en")
    assert calls == ["es"] and out.narrative == "old english"  # the same language is still served from cache


# ---- scan names and estimate wording ---------------------------------------------------------------------------

def test_the_scan_prompt_asks_for_local_names_only_in_another_language():
    import asyncio

    from app.services import gemini_service

    seen = []

    async def fake(payload, kind=None):
        seen.append(payload["contents"][0]["parts"][0]["text"])
        return {"candidates": [{"content": {"parts": [{"text": '[{"name": "rice", "estimated_grams": 100, "local_name": "arroz"}, {"name": "tea", "estimated_grams": 200, "local_name": "Tea"}]'}]}}]}

    original = gemini_service.generate_content
    gemini_service.generate_content = fake
    try:
        en = asyncio.run(gemini_service.identify_foods(b"x", "image/jpeg"))
        es = asyncio.run(gemini_service.identify_foods(b"x", "image/jpeg", lang="es"))
    finally:
        gemini_service.generate_content = original
    assert "local_name" not in seen[0] and "in Spanish" in seen[1]
    assert es[0]["name"] == "rice" and es[0]["local_name"] == "arroz"
    assert "local_name" not in es[1]  # the same as the English name: nothing to add


def test_a_scan_in_spanish_shows_the_local_name_and_keeps_searching_in_english(client, monkeypatch):
    from app.routers import photo_estimation
    from app.services import usda_service

    asked = {}

    async def fake_identify(image_bytes, mime_type, lang="en"):
        asked["lang"] = lang
        return [{"name": "rice", "estimated_grams": 150.0, **({"local_name": "arroz"} if lang != "en" else {})}]

    async def fake_search(query, page_size=10):
        asked["query"] = query
        return []

    async def fake_estimate(names, region=None, lang="en"):
        asked["estimate_names"], asked["estimate_lang"] = names, lang
        return {}

    monkeypatch.setattr(photo_estimation, "identify_foods", fake_identify)
    monkeypatch.setattr(photo_estimation, "estimate_foods", fake_estimate)
    monkeypatch.setattr(usda_service, "search_foods", fake_search)
    body = base64.b64encode(b"\xff\xd8\xffjpeg").decode()
    out = client.post("/estimate-photo", json={"image": body}, headers={"Accept-Language": "es"}).json()
    assert out[0]["name"] == "rice" and out[0]["display_name"] == "arroz"
    assert asked["lang"] == "es" and asked["estimate_names"] == ["rice"] and asked["estimate_lang"] == "es"
    assert "arroz" not in asked.get("query", "")

    english = client.post("/estimate-photo", json={"image": body}).json()
    assert english[0]["display_name"] is None


def test_the_estimate_default_wording_and_prompt_follow_the_language():
    from app.services.estimates import LANGUAGE_RULE, validate_estimate

    entry = {"calories_per_100g": 150, "protein_g": 3, "carbs_g": 27, "fat_g": 3.5}
    assert validate_estimate(entry)["basis"] == "A typical value for this dish."
    assert validate_estimate(entry, "fr")["basis"] == "Une valeur typique pour ce plat."
    assert "{language}" in LANGUAGE_RULE
