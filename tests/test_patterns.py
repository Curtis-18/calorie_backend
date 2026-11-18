"""Roadmap P2.3: patterns and the weekly summary."""

import uuid
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace

from app.services import patterns
from app.services.patterns import Entry, build_report, day_features, find_patterns

TODAY = date(2026, 11, 18)  # a Wednesday
BANNED = ["cheat", "bad", "guilt", "burn off", "earn", "punish", "make up for", "fail", "ruin", "lowest", "worst", "stop eating", "skip"]


def e(day, hour, meal="dinner", cal=500, protein=20.0, live=True):
    ts = datetime.combine(day if live else day + timedelta(days=2), time(hour, 0))
    return Entry(day, ts, meal, cal, protein)


def history(n, make):
    """[make(day)] for each of the n days ending today, flattened."""
    out = []
    for i in range(n):
        out.extend(make(TODAY - timedelta(days=i), i))
    return out


# ---- features ---------------------------------------------------------------

def test_a_day_with_no_calories_is_not_a_day():
    assert day_features([e(TODAY, 12, cal=0)]) == []


def test_only_live_entries_count_for_time_of_day():
    f = day_features([e(TODAY, 21, cal=300, live=False), e(TODAY, 12, cal=300)])[0]
    assert f.late_share == 0.0  # the 21:00 one was saved two days later: not trusted
    g = day_features([e(TODAY, 21, cal=300, live=False)])[0]
    assert g.late_share is None


def test_lunch_protein_is_none_without_a_lunch():
    assert day_features([e(TODAY, 19, meal="dinner")])[0].lunch_protein_g is None
    assert day_features([e(TODAY, 13, meal="lunch", protein=12)])[0].lunch_protein_g == 12


# ---- patterns ---------------------------------------------------------------

def _lunch_evening_history(n=20):
    # Even-numbered days: light lunch and a heavy 9 PM snack; odd: strong lunch, no late food.
    def make(day, i):
        if i % 2 == 0:
            return [e(day, 13, "lunch", 400, 10), e(day, 21, "snack", 600, 5)]
        return [e(day, 13, "lunch", 600, 40), e(day, 19, "dinner", 400, 20)]
    return history(n, make)


def test_the_lunch_protein_evening_pattern_is_found_with_real_numbers():
    found = find_patterns(day_features(_lunch_evening_history()))
    p = next(x for x in found if x.id == "lunch_protein_evening")
    assert "under 25 g of protein at lunch" in p.text
    assert "60%" in p.text and "0%" in p.text


def test_no_pattern_without_enough_days():
    assert find_patterns(day_features(_lunch_evening_history(10))) == []


def test_no_pattern_when_the_two_kinds_of_day_look_the_same():
    flat = history(20, lambda d, i: [e(d, 13, "lunch", 600, 10 if i % 2 else 40), e(d, 19, "dinner", 400, 20)])
    assert [p.id for p in find_patterns(day_features(flat))] == []


def test_not_enough_days_on_one_side_means_no_claim():
    # 3 light-lunch days only (< 4), the rest strong.
    def make(day, i):
        if i < 3:
            return [e(day, 13, "lunch", 400, 10), e(day, 21, "snack", 600, 5)]
        return [e(day, 13, "lunch", 600, 40), e(day, 19, "dinner", 400, 20)]
    assert all(p.id != "lunch_protein_evening" for p in find_patterns(day_features(history(20, make))))


def test_weekends_running_higher_is_found():
    def make(day, i):
        return [e(day, 13, "lunch", 2300 if day.weekday() >= 5 else 1900, 80)]
    found = find_patterns(day_features(history(28, make)))
    p = next(x for x in found if x.id == "weekend_higher")
    assert "21%" in p.text and "Weekend flex" in p.tip


def test_weekends_running_lower_is_not_reported():
    def make(day, i):
        return [e(day, 13, "lunch", 1500 if day.weekday() >= 5 else 2000, 80)]
    assert all(p.id != "weekend_higher" for p in find_patterns(day_features(history(28, make))))


def test_a_late_heavy_day_pattern():
    found = find_patterns(day_features(history(20, lambda d, i: [e(d, 12, "lunch", 600, 30), e(d, 21, "snack", 600, 10)])))
    assert any(p.id == "late_share" and "50%" in p.text for p in found)


def test_at_most_two_patterns_strongest_first():
    def make(day, i):
        weekend = day.weekday() >= 5
        if i % 2 == 0:
            return [e(day, 13, "lunch", 2300 if weekend else 1900, 10), e(day, 21, "snack", 800, 5)]
        return [e(day, 13, "lunch", 2300 if weekend else 1900, 40), e(day, 19, "dinner", 300, 20)]
    found = find_patterns(day_features(history(28, make)))
    assert 1 <= len(found) <= 2
    assert [p.strength for p in found] == sorted([p.strength for p in found], reverse=True)


def test_every_sentence_is_kind_and_never_tells_anyone_to_eat_less():
    candidates = []
    for maker in (
        lambda d, i: [e(d, 13, "lunch", 400, 10), e(d, 21, "snack", 600, 5)] if i % 2 == 0 else [e(d, 13, "lunch", 600, 40), e(d, 19, "dinner", 400, 20)],
        lambda d, i: [e(d, 13, "lunch", 2300 if d.weekday() >= 5 else 1900, 80)],
        lambda d, i: [e(d, 12, "lunch", 600, 30), e(d, 21, "snack", 600, 10)],
    ):
        candidates += find_patterns(day_features(history(28, maker)))
    assert len(candidates) >= 3
    for p in candidates:
        text = f"{p.text} {p.tip}".lower()
        assert not any(b in text for b in BANNED), text
    for n in range(0, 8):
        assert not any(b in patterns.summary_message(n).lower() for b in BANNED)


# ---- the weekly summary -------------------------------------------------------

def test_summary_counts_logged_days_and_protein_days():
    entries = history(7, lambda d, i: [e(d, 13, "lunch", 600, 120 if i < 3 else 40)])
    r = build_report(entries, TODAY, protein_target=120)
    assert r["days_logged"] == 7 and r["protein_goal_days"] == 3
    assert "7 of the last 7" in r["message"]
    assert r["patterns"] == [] and r["enough_data"] is False and r["days_needed"] == 7


def test_older_days_do_not_count_toward_this_week():
    entries = [e(TODAY - timedelta(days=10), 13, "lunch", 600, 120)]
    r = build_report(entries, TODAY, 120)
    assert r["days_logged"] == 0 and "fresh week" in r["message"]


def test_no_protein_target_means_no_protein_count():
    assert build_report([e(TODAY, 13, "lunch", 600, 50)], TODAY, None)["protein_goal_days"] is None


# ---- the route ----------------------------------------------------------------

class _Res:
    def __init__(self, rows=None, value=None):
        self.rows, self.value = rows or [], value

    def all(self):
        return self.rows

    def scalar_one_or_none(self):
        return self.value


class _Db:
    def __init__(self, *results):
        self.results = list(results)

    async def execute(self, stmt):
        return self.results.pop(0)


def _use(db):
    from app.core.database import get_db
    from app.main import app

    async def fake():
        yield db

    app.dependency_overrides[get_db] = fake


def test_the_route_returns_the_report(client, monkeypatch):
    from app.routers import reports

    monkeypatch.setattr(reports, "resolve_today", lambda d: TODAY)
    rows = [(TODAY, datetime.combine(TODAY, time(13)), "lunch", 600, 130.0)]
    _use(_Db(_Res(rows=rows), _Res(value=120)))
    r = client.get("/reports/weekly")
    assert r.status_code == 200
    body = r.json()
    assert body["days_logged"] == 1 and body["protein_goal_days"] == 1 and body["patterns"] == []


def test_the_route_works_with_no_plan_and_no_logs(client, monkeypatch):
    from app.routers import reports

    monkeypatch.setattr(reports, "resolve_today", lambda d: TODAY)
    _use(_Db(_Res(rows=[]), _Res(value=None)))
    body = client.get("/reports/weekly").json()
    assert body["days_logged"] == 0 and body["protein_goal_days"] is None


def test_the_route_needs_a_login(anon_client):
    assert anon_client.get("/reports/weekly").status_code == 401
