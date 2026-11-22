"""R9: movement logs, the weekly maths and the rough estimate."""

import re
import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.i18n import SUPPORTED
from app.services import movement as m
from app.services import workouts

ME = uuid.UUID("00000000-0000-0000-0000-000000000001")
SAM = uuid.UUID("00000000-0000-0000-0000-000000000002")
WED = date(2026, 11, 25)  # a Wednesday; its week starts Monday 23 Nov


def d(offset: int, base: date = WED) -> date:
    return base + timedelta(days=offset)


# --- the estimate -------------------------------------------------------------------------------------

def test_the_estimate_counts_only_what_is_above_rest_and_rounds_to_ten():
    assert m.estimate_kcal("walk", "moderate", 30, 70) == 90  # (3.5 - 1) x 70 x 0.5 = 87.5
    assert m.estimate_kcal("run", "hard", 30, 70) == 320
    assert m.estimate_kcal("walk", "easy", 1, 70) == 0 or m.estimate_kcal("walk", "easy", 1, 70) is not None


@pytest.mark.parametrize("args", [("walk", "moderate", 30, None), ("walk", "moderate", 30, 0), ("nope", "easy", 30, 70),
                                  ("walk", "fast", 30, 70), ("walk", "easy", 0, 70)])
def test_no_estimate_when_something_is_not_known(args):
    assert m.estimate_kcal(*args) is None


def test_a_longer_or_harder_effort_never_estimates_less():
    for key in m.ACTIVITIES:
        easy, mod, hard = (m.estimate_kcal(key, i, 30, 70) for i in m.INTENSITIES)
        assert easy <= mod <= hard, key
        assert m.estimate_kcal(key, "moderate", 60, 70) >= m.estimate_kcal(key, "moderate", 30, 70)


def test_every_activity_belongs_to_a_slice_and_the_hand_list_has_each_slice():
    assert {v[1] for v in m.ACTIVITIES.values()} == set(m.SLICES)
    assert {m.slice_for(k) for k in m.manual_choices()} == set(m.SLICES)
    assert all(not k.startswith("session_") for k in m.manual_choices())


def test_sessions_take_their_effort_from_the_routine_level():
    assert m.session_activity(workouts.get("strength_30")) == "session_strength"
    assert m.session_intensity(workouts.get("strength_30")) == "hard"
    assert m.session_intensity(workouts.get("walk_15")) == "easy"
    assert m.session_intensity(workouts.get("full_15")) == "moderate"
    assert m.session_activity(workouts.get("dance_3")) == "session_fun"


def test_nothing_in_the_activity_names_is_about_burning_or_earning_and_all_are_translated():
    from app.i18n import TABLES

    for key, (label, *_rest) in m.ACTIVITIES.items():
        assert not re.search(r"kcal|calor|burn|earn|diet|cheat|guilt|punish", label, re.I), key
        for lang in SUPPORTED:
            if lang != "en":
                assert label in TABLES[lang], (lang, label)


# --- the week --------------------------------------------------------------------------------------------

def test_the_week_starts_on_monday():
    assert m.week_start(WED) == date(2026, 11, 23)
    assert m.week_start(date(2026, 11, 22)) == date(2026, 11, 16)  # a Sunday belongs to the week before
    assert m.week_start(date(2026, 11, 23)) == date(2026, 11, 23)


def test_summarising_the_week_adds_up_and_ignores_other_weeks():
    rows = [
        (d(-2), "strength", 20),  # Monday
        (d(0), "cardio", 30),     # today
        (d(0), "fun", 5),
        (d(-3), "mobility", 99),  # the Sunday before: another week
        (d(5), "cardio", 50),     # next week
    ]
    w = m.summarise_week(rows, WED)
    assert (w["minutes"], w["sessions"], w["active_days"], w["strength_days"]) == (55, 3, 2, 1)
    assert w["moved_days"] == [True, False, True, False, False, False, False] and w["today_index"] == 2
    assert w["by_slice"]["cardio"] == {"minutes": 30, "sessions": 1} and w["by_slice"]["mobility"] == {"minutes": 0, "sessions": 0}
    assert (w["today_minutes"], w["today_sessions"]) == (35, 2)
    assert (w["goal_minutes"], w["strength_days_goal"], w["week_moved"]) == (150, 2, False)


def test_an_empty_week_is_zeros_not_an_error():
    w = m.summarise_week([], WED)
    assert w["minutes"] == 0 and w["moved_days"] == [False] * 7 and w["week_moved"] is False


def test_a_moved_week_is_about_half_the_guide_or_three_active_days():
    assert not m.is_moved_week(74, 2) and m.is_moved_week(75, 1) and m.is_moved_week(30, 3)
    assert m.GENTLE_WEEK_MINUTES * 2 == 150 or m.GENTLE_WEEK_MINUTES < m.WEEK_GUIDE_MINUTES


# --- the run of moved weeks --------------------------------------------------------------------------------

def week_rows(weeks_ago: int, minutes: int = 80, base: date = WED):
    return [(m.week_start(base) - timedelta(weeks=weeks_ago), "cardio", minutes)]


def test_no_movement_is_no_run():
    assert m.moved_weeks([], WED) == 0


def test_a_week_in_progress_that_already_counts_is_the_first_link():
    assert m.moved_weeks(week_rows(0), WED) == 1
    assert m.moved_weeks(week_rows(0) + week_rows(1) + week_rows(2), WED) == 3


def test_a_week_in_progress_that_does_not_count_yet_is_not_a_break():
    rows = week_rows(1) + week_rows(2) + week_rows(3)
    assert m.moved_weeks(rows, WED) == 3  # this week is just not done yet


def test_two_weeks_without_much_ends_the_run():
    rows = week_rows(3) + week_rows(4) + week_rows(5)
    assert m.moved_weeks(rows, WED) == 0


def test_one_missed_week_is_forgiven_but_adds_nothing():
    rows = week_rows(0) + week_rows(1) + week_rows(3) + week_rows(4)  # week 2 missed
    assert m.moved_weeks(rows, WED) == 4


def test_a_second_miss_so_soon_does_end_it():
    rows = week_rows(0) + week_rows(2) + week_rows(4)  # weeks 1 and 3 missed
    assert m.moved_weeks(rows, WED) == 2  # this week and week 2; the second miss ends it


def test_forgiveness_is_available_again_after_four_moved_weeks():
    # moved: 0,1,2,3 | missed 4 (forgiven) | moved 5,6,7,8 | missed 9 (forgiven) | moved 10
    moved = [0, 1, 2, 3, 5, 6, 7, 8, 10]
    rows = [r for w in moved for r in week_rows(w)]
    assert m.moved_weeks(rows, WED) == len(moved)


def test_a_missed_week_at_the_far_end_is_not_counted_as_a_link():
    assert m.moved_weeks(week_rows(0) + week_rows(1) + week_rows(2), WED) == 3
    rows = week_rows(0) + week_rows(1) + week_rows(3)  # miss at 2 then nothing older but week 3: forgiven link
    assert m.moved_weeks(rows, WED) == 3


def test_three_light_active_days_make_a_moved_week_even_with_few_minutes():
    rows = [(d(-2), "mobility", 10), (d(-1), "mobility", 10), (d(0), "mobility", 10)]
    assert m.moved_weeks(rows, WED) == 1


def test_unknown_slices_are_ignored():
    assert m.moved_weeks([(d(0), "swimming", 500)], WED) == 0


# --- the routes ----------------------------------------------------------------------------------------------

class _Result:
    def __init__(self, value=None, rows=None, rowcount=1):
        self.value, self.rows, self.rowcount = value, rows or [], rowcount

    def scalar_one_or_none(self):
        return self.value

    def scalars(self):
        return SimpleNamespace(all=lambda: self.rows)

    def all(self):
        return self.rows


class _Nested:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _Db:
    def __init__(self, *results, fail_on=None):
        self.results, self.statements = list(results), []
        self.committed = self.rolled_back = False
        self.fail_on = fail_on

    def begin_nested(self):
        return _Nested()

    async def execute(self, stmt):
        self.statements.append(str(stmt))
        if self.fail_on is not None and len(self.statements) == self.fail_on:
            raise RuntimeError('relation "movement_logs" does not exist')
        return self.results.pop(0)

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


def _with_db(db):
    from app.core.database import get_db
    from app.main import app

    async def fake_db():
        yield db

    app.dependency_overrides[get_db] = fake_db


def today():
    return datetime.now(timezone.utc).date()


def test_logging_a_guided_session_takes_its_slice_and_effort_from_the_routine(client):
    mid = uuid.uuid4()
    db = _Db(_Result(None), _Result(70.0), _Result())  # no existing row, my weight, the insert
    _with_db(db)
    r = client.post("/movement", json={"id": str(mid), "routine_id": "strength_30", "minutes": 28})
    assert r.status_code == 200
    out = r.json()
    assert (out["slice"], out["activity"], out["intensity"], out["source"], out["routine_id"]) == ("strength", "session_strength", "hard", "session", "strength_30")
    assert out["minutes"] == 28 and out["est_kcal"] == m.estimate_kcal("session_strength", "hard", 28, 70.0)
    assert out["label"] == "Strength session" and out["date"] == str(today())
    assert db.committed and any("INSERT INTO movement_logs" in s for s in db.statements)


def test_logging_by_hand_needs_an_activity_from_the_list(client):
    _with_db(_Db(_Result(None)))
    assert client.post("/movement", json={"id": str(uuid.uuid4()), "activity": "teleport", "minutes": 10}).status_code == 422
    _with_db(_Db(_Result(None)))
    assert client.post("/movement", json={"id": str(uuid.uuid4()), "activity": "session_cardio", "minutes": 10}).status_code == 422, "sessions are not logged by hand"
    _with_db(_Db(_Result(None)))
    assert client.post("/movement", json={"id": str(uuid.uuid4()), "minutes": 10}).status_code == 422


def test_a_hand_logged_walk_with_no_weight_known_has_no_estimate(client):
    _with_db(_Db(_Result(None), _Result(None), _Result()))
    r = client.post("/movement", json={"id": str(uuid.uuid4()), "activity": "walk", "minutes": 40, "intensity": "easy"})
    assert r.status_code == 200
    out = r.json()
    assert (out["slice"], out["source"], out["est_kcal"], out["intensity"]) == ("cardio", "manual", None, "easy")


@pytest.mark.parametrize("body", [
    {"minutes": 0}, {"minutes": 601}, {"minutes": 10, "intensity": "extreme"}, {"minutes": 10, "routine_id": "nope"},
])
def test_bad_requests_are_refused_and_write_nothing(client, body):
    db = _Db(_Result(None))
    _with_db(db)
    r = client.post("/movement", json={"id": str(uuid.uuid4()), "activity": "walk", **body})
    assert r.status_code == 422 and not db.committed


def test_a_date_far_from_today_is_refused(client):
    _with_db(_Db(_Result(None)))
    far = str(today() - timedelta(days=9))
    assert client.post("/movement", json={"id": str(uuid.uuid4()), "activity": "walk", "minutes": 10, "date": far}).status_code == 422


def test_repeating_the_same_id_returns_the_original_and_writes_nothing(client):
    mid = uuid.uuid4()
    row = SimpleNamespace(id=mid, user_id=ME, log_date=today(), slice="cardio", activity="walk", minutes=20, intensity="easy",
                          routine_id=None, source="manual", est_kcal=40, created_at=None)
    db = _Db(_Result(row))
    _with_db(db)
    r = client.post("/movement", json={"id": str(mid), "activity": "run", "minutes": 99})
    assert r.status_code == 200 and r.json()["activity"] == "walk" and not db.committed


def test_someone_elses_id_is_refused(client):
    row = SimpleNamespace(id=uuid.uuid4(), user_id=SAM, log_date=today(), slice="cardio", activity="walk", minutes=20,
                          intensity="easy", routine_id=None, source="manual", est_kcal=None, created_at=None)
    _with_db(_Db(_Result(row)))
    assert client.post("/movement", json={"id": str(row.id), "activity": "walk", "minutes": 20}).status_code == 409


def test_a_failed_save_is_a_clean_500_with_a_rollback(client):
    class Boom(_Db):
        async def commit(self):
            raise RuntimeError("db down")

    db = Boom(_Result(None), _Result(None), _Result())
    _with_db(db)
    r = client.post("/movement", json={"id": str(uuid.uuid4()), "activity": "walk", "minutes": 20})
    assert r.status_code == 500 and db.rolled_back


def test_the_list_and_a_missing_table(client):
    row = SimpleNamespace(id=uuid.uuid4(), user_id=ME, log_date=today(), slice="fun", activity="dance", minutes=15,
                          intensity="moderate", routine_id=None, source="manual", est_kcal=70, created_at=None)
    _with_db(_Db(_Result(rows=[row])))
    r = client.get("/movement")
    assert r.status_code == 200 and r.json()[0]["label"] == "Dance" and r.json()[0]["slice"] == "fun"
    _with_db(_Db(fail_on=1))
    assert client.get("/movement").json() == []


def test_the_week_route(client):
    rows = [(today(), "strength", 20), (today(), "cardio", 60)]
    _with_db(_Db(_Result(rows=rows)))
    r = client.get("/movement/week")
    assert r.status_code == 200
    w = r.json()
    assert w["minutes"] == 80 and w["week_moved"] is True and w["streak"] == 1 and w["today_minutes"] == 80
    assert w["by_slice"]["strength"] == {"minutes": 20, "sessions": 1} and len(w["moved_days"]) == 7
    assert w["goal_minutes"] == 150 and w["strength_days"] == 1


def test_the_week_with_a_missing_table_is_an_empty_week_not_an_error(client):
    _with_db(_Db(fail_on=1))
    r = client.get("/movement/week")
    assert r.status_code == 200 and r.json()["minutes"] == 0 and r.json()["streak"] == 0


def test_deleting_only_removes_your_own(client):
    db = _Db(_Result(rowcount=1))
    _with_db(db)
    assert client.delete(f"/movement/{uuid.uuid4()}").status_code == 204 and db.committed
    _with_db(_Db(_Result(rowcount=0)))
    assert client.delete(f"/movement/{uuid.uuid4()}").status_code == 404


def test_the_choices_for_logging_by_hand(client):
    body = client.get("/movement/choices").json()
    keys = [a["key"] for a in body["activities"]]
    assert keys == m.manual_choices() and "session_cardio" not in keys
    assert body["intensities"] == ["easy", "moderate", "hard"]
    es = client.get("/movement/choices", headers={"Accept-Language": "es"}).json()
    assert es["activities"][0]["label"] != body["activities"][0]["label"]


def test_every_route_needs_a_login():
    from fastapi.testclient import TestClient

    from app.main import app

    app.dependency_overrides.clear()
    c = TestClient(app)
    for method, path in [("get", "/movement"), ("get", "/movement/week"), ("get", "/movement/choices"),
                         ("post", "/movement"), ("delete", f"/movement/{uuid.uuid4()}")]:
        assert getattr(c, method)(path).status_code in (401, 403, 422), path


# ---- the coach and Insights hear about movement, as context only --------------------------------

import asyncio


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


def test_the_weekly_snapshot_adds_up_this_week_only():
    from app.services import movement_read

    rows = [(WED, "cardio", 30), (WED, "fun", 10), (d(-1), "strength", 20), (d(-4), "cardio", 99)]  # last one is last week
    db = _Db(_Rows([r for r in rows if r[0] >= m.week_start(WED)]))
    snap = asyncio.run(movement_read.week_snapshot(db, ME, WED))
    assert snap == {"today_minutes": 40, "week_minutes": 60, "active_days": 2, "sessions": 3}


def test_the_weekly_snapshot_never_raises_and_is_zero_without_the_table():
    from app.services import movement_read

    assert asyncio.run(movement_read.week_snapshot(_Db(fail_on=1), ME, WED)) == movement_read.NOTHING

    class NoSavepoint:  # a fake that can't even open one
        pass

    assert asyncio.run(movement_read.week_snapshot(NoSavepoint(), ME, WED)) == movement_read.NOTHING


def _context(movement):
    from app.services import coach_prompt

    return coach_prompt.build_context(
        goal="lose", calorie_target=1800, floor=1500, protein_g=120, carbs_g=200, fat_g=60,
        today_entries=[], today_totals={"calories": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0},
        allowance_today=None, week=[], region=None, recipes=[], movement=movement,
    )


def test_the_coach_is_told_the_movement_only_when_there_is_some():
    assert "Movement they logged" not in _context(None)
    assert "Movement they logged" not in _context({"today_minutes": 0, "week_minutes": 0, "active_days": 0})
    text = _context({"today_minutes": 25, "week_minutes": 80, "active_days": 3})
    assert "today 25 min; this week 80 min on 3 day(s)" in text
    # Never a calorie figure for it.
    assert not re.search(r"movement[^\n]*kcal", text, re.I)


def test_the_coach_rules_keep_movement_apart_from_food():
    from app.services import coach_prompt

    rule = coach_prompt.SYSTEM_PROMPT
    assert "never suggest eating more or less because of it" in rule and "never give it a calorie value" in rule
