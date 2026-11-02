from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app.services.progress_service import LogRow, best_weekly_run, compute_progress
from app.services.weight_service import WeighIn, summarize, sync_targets_to_weight, with_trend

TODAY = date(2026, 11, 2)


def d(offset: int) -> date:
    return TODAY - timedelta(days=offset)


# --- trend and summary ---------------------------------------------------------


def test_first_point_is_its_own_trend_and_input_order_does_not_matter():
    pts = with_trend([WeighIn(d(0), 80.0), WeighIn(d(1), 81.0)])
    assert [p["date"] for p in pts] == [d(1), d(0)]
    assert pts[0]["trend_kg"] == 81.0
    # one day later the trend moves 10% of the way: 81 + 0.1 * (80 - 81)
    assert pts[1]["trend_kg"] == pytest.approx(80.9)


def test_trend_weights_gaps_between_weigh_ins():
    # 7 days apart: the trend moves 1 - 0.9^7 = 52% of the way.
    pts = with_trend([WeighIn(d(7), 90.0), WeighIn(d(0), 80.0)])
    assert pts[1]["trend_kg"] == pytest.approx(90 - 0.5217 * 10, abs=0.01)


def test_trend_smooths_a_single_heavy_morning():
    days = [WeighIn(d(10 - i), 80.0 - 0.1 * i) for i in range(10)]
    days.append(WeighIn(d(0), 82.0))  # water weight spike
    pts = with_trend(days)
    assert pts[-1]["weight_kg"] == 82.0
    assert pts[-1]["trend_kg"] < 80.0, "one spike shouldn't erase the downward trend"


def test_summary_reports_trend_change_and_raw_change():
    pts = with_trend([WeighIn(d(30), 90.0), WeighIn(d(15), 87.0), WeighIn(d(3), 85.0)])
    s = summarize(pts, TODAY)
    assert s["start_kg"] == 90.0 and s["start_date"] == d(30)
    assert s["current_kg"] == 85.0 and s["days_since_last"] == 3
    assert s["raw_change_kg"] == -5.0
    assert -5.0 < s["change_kg"] < 0
    assert (s["lowest_kg"], s["highest_kg"], s["count"]) == (85.0, 90.0, 3)
    assert summarize([], TODAY) is None


# --- targets follow the newest weight ------------------------------------------


class _TargetOnly:
    def __init__(self, target):
        self.target = target

    async def execute(self, _stmt):
        target = self.target

        class _R:
            def scalar_one_or_none(self):
                return target

        return _R()


def _target(**kw):
    base = dict(
        date_of_birth=date(1990, 1, 1), sex="female", height_cm=165.0, weight_kg=80.0,
        activity_level="light", goal="lose", bmr=0, tdee=0, calorie_target=0,
        protein_g=0, fat_g=0, carbs_g=0,
    )
    base.update(kw)
    return SimpleNamespace(**base)


async def test_weigh_in_recomputes_targets_for_the_new_weight():
    t = _target(weight_kg=80.0)
    updated, notice = await sync_targets_to_weight(_TargetOnly(t), "u", 74.0)
    assert updated and notice is None
    assert t.weight_kg == 74.0
    assert t.goal == "lose"
    assert t.calorie_target >= 1200 and t.protein_g > 0


async def test_reaching_the_bottom_of_the_healthy_range_switches_to_maintain():
    t = _target(weight_kg=55.0)
    updated, notice = await sync_targets_to_weight(_TargetOnly(t), "u", 49.0)  # BMI 18.0
    assert updated
    assert t.goal == "maintain"
    assert "Maintain" in notice


async def test_no_targets_yet_means_nothing_to_sync():
    assert await sync_targets_to_weight(_TargetOnly(None), "u", 70.0) == (False, None)


# --- progress: weigh-in XP and badges --------------------------------------------


def test_weigh_ins_earn_xp_and_badges():
    p = compute_progress([], TODAY, 2000, 120, weigh_in_dates=[d(0), d(7), d(14), d(21)])
    assert p["level"]["xp"] == 40
    assert p["today"]["xp"] == 10
    badges = {a["id"]: a for a in p["achievements"]}
    assert badges["on_the_scale"]["unlocked_on"] == d(21)
    assert badges["check_in_champ"]["unlocked"] is True
    assert badges["check_in_champ"]["unlocked_on"] == d(0)


def test_weigh_ins_do_not_count_toward_the_food_streak():
    p = compute_progress([], TODAY, 2000, 120, weigh_in_dates=[d(0), d(1), d(2)])
    assert p["streak"]["current"] == 0


def test_future_weigh_ins_are_ignored():
    p = compute_progress(
        [LogRow(TODAY, "lunch", "manual", 500, 20.0)], TODAY, 2000, 120,
        weigh_in_dates=[TODAY + timedelta(days=1)],
    )
    assert p["level"]["xp"] == 12


def test_weekly_run_spans_a_year_boundary_and_breaks_on_a_missed_week():
    run, reached = best_weekly_run(
        [date(2025, 12, 15), date(2025, 12, 22), date(2025, 12, 29), date(2026, 1, 5)]
    )
    assert run == 4 and reached == date(2026, 1, 5)
    run, reached = best_weekly_run([date(2026, 1, 5), date(2026, 1, 12), date(2026, 1, 26)])
    assert run == 2 and reached is None


# --- endpoints -------------------------------------------------------------------


def test_weight_routes_require_auth(anon_client):
    assert anon_client.get("/weights").status_code == 401
    assert anon_client.post("/weights", json={"weight_kg": 70}).status_code == 401
    assert anon_client.delete("/weights/2026-11-02").status_code == 401


def test_implausible_weights_are_rejected(client):
    assert client.post("/weights", json={"weight_kg": 5}).status_code == 422
    assert client.post("/weights", json={"weight_kg": 900}).status_code == 422


class _ScriptedDb:
    """Answers each execute() in order with the next scripted result."""

    def __init__(self, *results):
        self.results = list(results)
        self.statements = []
        self.committed = False

    async def execute(self, stmt):
        self.statements.append(str(stmt))
        data = self.results.pop(0) if self.results else None

        class _R:
            rowcount = 1

            def all(self):
                return data or []

            def first(self):
                return data

            def scalar_one_or_none(self):
                return data

        return _R()

    async def commit(self):
        self.committed = True


def _use(db, monkeypatch):
    from app.core.database import get_db
    from app.main import app
    from app.routers import weights

    monkeypatch.setattr(weights, "resolve_today", lambda _date: TODAY)

    async def fake_db():
        yield db

    app.dependency_overrides[get_db] = fake_db


def test_logging_todays_weight_updates_targets_and_returns_history(client, monkeypatch):
    target = _target(weight_kg=80.0)
    db = _ScriptedDb(
        None,                               # upsert
        (TODAY, 78.0),                      # latest weigh-in is today
        target,                             # targets row
        [(d(10), 80.0), (TODAY, 78.0)],     # history
    )
    _use(db, monkeypatch)

    r = client.post("/weights", json={"weight_kg": 78.0})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["targets_updated"] is True
    assert target.weight_kg == 78.0
    assert db.committed
    assert [e["weight_kg"] for e in body["history"]["entries"]] == [80.0, 78.0]
    assert body["history"]["summary"]["raw_change_kg"] == -2.0
    assert "ON CONFLICT" in db.statements[0].upper()


def test_backfilling_an_old_weigh_in_leaves_targets_alone(client, monkeypatch):
    db = _ScriptedDb(None, (TODAY, 78.0), [(d(5), 79.0), (TODAY, 78.0)])
    _use(db, monkeypatch)

    r = client.post("/weights", json={"weight_kg": 79.0, "date": d(5).isoformat()})

    assert r.status_code == 200
    assert r.json()["targets_updated"] is False


def test_a_weigh_in_dated_in_the_future_is_rejected(client, monkeypatch):
    _use(_ScriptedDb(), monkeypatch)
    r = client.post("/weights", json={"weight_kg": 70, "date": (TODAY + timedelta(days=3)).isoformat()})
    assert r.status_code == 422
