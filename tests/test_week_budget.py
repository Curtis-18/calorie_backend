"""Roadmap P2: weekly calorie banking and the gentle nudge."""

import itertools
import uuid
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app.services.target_calculator import MIN_CALORIES
from app.services.week_budget import (
    DAYS, MAX_BONUS, MAX_TRIM, compute_nudge, compute_week_budget, valid_weights, week_start_of,
)

MON = date(2026, 11, 16)  # a Monday


def _week(today, eaten, target=2000, floor=1500, **kw):
    return compute_week_budget(today=today, target=target, floor=floor, eaten_by_date=eaten, **kw)


# ---- the maths --------------------------------------------------------------

def test_a_normal_week_changes_nothing():
    eaten = {MON + timedelta(days=i): 2000 for i in range(3)}
    w = _week(MON + timedelta(days=3), eaten)
    assert w.today.allowance == 2000 and w.bank == 0


def test_a_bigger_day_eases_today_a_little():
    w = _week(MON + timedelta(days=1), {MON: 2600})  # 600 over, 6 days left (incl. today)
    assert w.bank == -600
    assert w.today.allowance == 2000 - 100


def test_a_lighter_day_gives_a_little_room_back():
    w = _week(MON + timedelta(days=1), {MON: 1700})
    assert w.bank == 300 and w.today.allowance == 2050


def test_the_ease_is_capped_at_fifteen_percent():
    w = _week(MON + timedelta(days=5), {MON: 4000, MON + timedelta(days=1): 4000})  # 2 days left
    assert w.today.allowance == 1700  # 2000 x 0.85, not 1000


def test_never_below_the_floor_even_when_the_trim_would_allow_it():
    # Target 1600, floor 1500: 15% below would be 1360, but the floor wins.
    w = _week(MON + timedelta(days=5), {MON: 4000}, target=1600, floor=1500)
    assert w.today.allowance == 1500


def test_a_person_at_the_floor_is_never_trimmed():
    w = _week(MON + timedelta(days=2), {MON: 3000, MON + timedelta(days=1): 3000}, target=1200, floor=1200)
    assert w.today.allowance == 1200


def test_unlogged_days_neither_bank_nor_owe():
    w = _week(MON + timedelta(days=4), {})
    assert w.bank == 0 and w.today.allowance == 2000
    assert [d.state for d in w.days[:4]] == ["past_unlogged"] * 4


def test_eating_under_the_floor_earns_nothing_extra():
    w = _week(MON + timedelta(days=1), {MON: 600})  # counted as 1500, so +500 not +1400
    assert w.bank == 500


def test_the_bank_is_capped_at_one_days_target():
    eaten = {MON + timedelta(days=i): 1500 for i in range(5)}  # +2500 raw
    w = _week(MON + timedelta(days=5), eaten)
    assert w.bank == 2000


def test_the_days_and_states_of_a_week():
    w = _week(MON + timedelta(days=2), {MON: 2000})
    assert w.week_start == MON and len(w.days) == 7
    assert [d.state for d in w.days] == ["past_logged", "past_unlogged", "today", "future", "future", "future", "future"]


def test_week_can_start_on_any_day_and_never_splits():
    sunday_start = week_start_of(date(2026, 11, 18), 6)
    assert sunday_start == date(2026, 11, 15) and sunday_start.weekday() == 6
    assert week_start_of(MON, 0) == MON
    assert week_start_of(MON + timedelta(days=6), 0) == MON


def test_weekend_flex_plans_bigger_weekend_days():
    weights = [0.94] * 5 + [1.15, 1.15]  # adds to 7
    assert valid_weights(weights, 2000, 1500)
    w = _week(MON + timedelta(days=5), {}, weights=weights)
    assert w.days[5].base == 2300 and w.days[0].base == 1880
    assert sum(d.base for d in w.days) == pytest.approx(14000, abs=7)


@pytest.mark.parametrize("weights", [
    [1] * 6, [1] * 8, [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.5], [0.5, 1.5] + [1.0] * 5,
    [1.2, 1.2, 1.0, 1.0, 1.0, 1.0, 0.6], [1.1] * 7, ["a"] * 7,
])
def test_bad_weights_are_refused(weights):
    assert not valid_weights(weights, 2000, 1500)


def test_weights_cannot_put_a_day_under_the_floor():
    # 1600 target: a 0.85 weight would be 1360 < floor 1500
    assert not valid_weights([0.85, 1.15, 1.0, 1.0, 1.0, 1.0, 1.0], 1600, 1500)
    assert valid_weights([0.94, 1.06, 1.0, 1.0, 1.0, 1.0, 1.0], 1600, 1500)


def test_bad_weights_fall_back_to_plain_days():
    assert _week(MON, {}, weights=[3.0] * 7).today.base == 2000


def test_sweep_the_allowance_always_stays_inside_the_limits():
    """Every target, day of week and mix of logged, light, heavy and missing days."""
    patterns = [None, 0.4, 0.8, 1.0, 1.3, 2.0]
    checked = 0
    for sex, target in itertools.product(MIN_CALORIES, (1200, 1450, 1800, 2400, 3200)):
        floor = MIN_CALORIES[sex]
        if target < floor:
            continue
        for today_i in range(7):
            for combo in itertools.islice(itertools.product(patterns, repeat=min(today_i, 4)), 400):
                eaten = {}
                for i, mult in enumerate(combo):
                    if mult is not None:
                        eaten[MON + timedelta(days=i)] = round(target * mult)
                w = _week(MON + timedelta(days=today_i), eaten, target=target, floor=floor)
                a = w.today.allowance
                assert a >= floor
                assert a >= round(target * (1 - MAX_TRIM)) - 1 or a >= floor
                assert a <= round(target * (1 + MAX_BONUS)) + 1
                assert w.bank <= target
                checked += 1
    assert checked > 1000


# ---- the nudge -----------------------------------------------------------------

BANNED = ["cheat", "bad", "guilt", "burn off", "earn", "punish", "make up for", "fail", "ruin", "sin"]


def _nudge(eaten, allowance=2000, left=4, target=2000, floor=1500, goal="maintain"):
    return compute_nudge(shown_allowance=allowance, eaten_today=eaten, days_left_after_today=left,
                         target=target, floor=floor, goal=goal)


def test_the_example_from_the_plan():
    n = _nudge(2400, left=4)
    assert n.kind == "spread" and n.over_by == 400 and n.per_day == 100 and n.days == 4
    assert n.message == "You're about 400 over today. Want to ease about 100 a day over the next 4 days?"


def test_small_overages_say_nothing():
    assert _nudge(2150) is None   # under 150
    assert _nudge(2000) is None
    assert _nudge(1200) is None


def test_no_nudge_on_the_last_day_or_for_a_gain_goal():
    assert _nudge(3000, left=0) is None
    assert _nudge(3000, goal="gain") is None


def test_a_single_day_left_is_worded_in_the_singular():
    assert "over the next 1 day?" in _nudge(2200, left=1).message


def test_too_big_to_spread_offers_nothing():
    n = _nudge(3600, left=2)  # 800 per day > 15% of 2000
    assert n.kind == "too_big" and n.per_day is None
    assert "normal day tomorrow" in n.message


def test_a_person_at_the_floor_is_never_asked_to_trim():
    n = _nudge(1700, allowance=1200, target=1200, floor=1200, left=3)
    assert n.kind == "too_big" and n.per_day is None


def test_the_suggested_trim_never_breaks_the_limits_and_the_words_stay_kind():
    for target, floor, over, left in itertools.product((1200, 1600, 2000, 3000), (1200, 1500), range(160, 2000, 90), range(1, 7)):
        if target < floor:
            continue
        n = _nudge(target + over, allowance=target, target=target, floor=floor, left=left)
        if n is None:
            continue
        if n.per_day is not None:
            assert n.per_day <= target * MAX_TRIM + 10
            assert target - n.per_day >= floor - 10
        text = n.message.lower()
        assert not any(b in text for b in BANNED), text


# ---- the routes ----------------------------------------------------------------

ME = uuid.UUID("00000000-0000-0000-0000-000000000001")


class _Ctx:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *a):
        return False


class _Res:
    def __init__(self, value=None, rows=None):
        self.value, self.rows = value, rows or []

    def scalar_one_or_none(self):
        return self.value

    def all(self):
        return self.rows


class _Db:
    def __init__(self, *results):
        self.results, self.statements, self.committed = list(results), [], False

    def begin_nested(self):
        return _Ctx()

    async def execute(self, stmt):
        self.statements.append(stmt)
        return self.results.pop(0)

    async def commit(self):
        self.committed = True


def _target(goal="maintain", sex="male", calories=2000):
    return SimpleNamespace(calorie_target=calories, sex=sex, goal=goal)


def _prefs(**kw):
    base = dict(mode="weekly", week_start_day=0, weights=None, nudges=False, dismissed_weeks=[])
    return SimpleNamespace(**{**base, **kw})


def _use(db):
    from app.core.database import get_db
    from app.main import app

    async def fake():
        yield db

    app.dependency_overrides[get_db] = fake


def _freeze_today(monkeypatch, day):
    from app.routers import budget

    monkeypatch.setattr(budget, "resolve_today", lambda client_date: day)


def test_week_route_in_weekly_mode(client, monkeypatch):
    _freeze_today(monkeypatch, MON + timedelta(days=1))
    _use(_Db(_Res(_target()), _Res(_prefs()), _Res(rows=[(MON, 2600)])))
    r = client.get("/budget/week")
    assert r.status_code == 200
    body = r.json()
    assert body["allowance_today"] == 1900 and body["bank"] == -600 and body["mode"] == "weekly"
    assert body["days"][0]["eaten"] == 2600 and body["days"][1]["state"] == "today"
    assert "a little lower" in body["explanation"] and body["nudge"] is None


def test_week_route_in_daily_mode_shows_the_plain_target(client, monkeypatch):
    _freeze_today(monkeypatch, MON + timedelta(days=1))
    _use(_Db(_Res(_target()), _Res(_prefs(mode="daily")), _Res(rows=[(MON, 2600)])))
    body = client.get("/budget/week").json()
    assert body["allowance_today"] == 2000 and body["explanation"] == "Your target is the same every day."


def test_week_route_without_prefs_table_still_works(client, monkeypatch):
    _freeze_today(monkeypatch, MON)

    class Broken(_Db):
        def begin_nested(self):
            raise RuntimeError("relation budget_prefs does not exist")

    _use(Broken(_Res(_target()), _Res(rows=[])))
    body = client.get("/budget/week").json()
    assert body["mode"] == "daily" and body["allowance_today"] == 2000


def test_the_nudge_shows_only_when_switched_on_and_not_declined(client, monkeypatch):
    today = MON + timedelta(days=2)
    _freeze_today(monkeypatch, today)
    rows = [(today, 2500)]
    _use(_Db(_Res(_target()), _Res(_prefs(mode="daily", nudges=True)), _Res(rows=rows)))
    n = client.get("/budget/week").json()["nudge"]
    assert n["kind"] == "spread" and n["days"] == 4 and n["per_day"] == 130

    _use(_Db(_Res(_target()), _Res(_prefs(mode="daily", nudges=False)), _Res(rows=rows)))
    assert client.get("/budget/week").json()["nudge"] is None

    _use(_Db(_Res(_target()), _Res(_prefs(mode="daily", nudges=True, dismissed_weeks=[MON.isoformat()])), _Res(rows=rows)))
    assert client.get("/budget/week").json()["nudge"] is None


def test_week_needs_a_plan(client, monkeypatch):
    _freeze_today(monkeypatch, MON)
    _use(_Db(_Res(None)))
    assert client.get("/budget/week").status_code == 404


def test_prefs_default_to_daily(client):
    _use(_Db(_Res(None)))
    assert client.get("/budget/prefs").json() == {
        "mode": "daily", "week_start_day": 0, "weights": None, "nudges": False, "dismissed_weeks": []}


def test_prefs_are_saved_and_returned(client):
    db = _Db(_Res(None), _Res(None), _Res(_prefs(mode="weekly", nudges=True)))
    _use(db)
    r = client.post("/budget/prefs", json={"mode": "weekly", "nudges": True})
    assert r.status_code == 200 and r.json()["mode"] == "weekly" and db.committed


def test_bad_weekday_amounts_are_refused_before_anything_is_saved(client):
    db = _Db(_Res(None), _Res(_target()))
    _use(db)
    r = client.post("/budget/prefs", json={"weights": [1.5, 0.5, 1, 1, 1, 1, 1]})
    assert r.status_code == 422 and not db.committed


def test_prefs_validate_their_fields(client):
    _use(_Db(_Res(None)))
    assert client.post("/budget/prefs", json={"week_start_day": 7}).status_code == 422
    assert client.post("/budget/prefs", json={"mode": "monthly"}).status_code == 422


def test_budget_needs_a_login(anon_client):
    assert anon_client.get("/budget/week").status_code == 401
