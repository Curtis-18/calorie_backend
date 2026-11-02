from datetime import date, datetime, timedelta

from app.services.progress_service import (
    MAX_FREEZES,
    LogRow,
    compute_progress,
    level_for,
    tier_for,
    xp_for_level,
)

TODAY = date(2026, 11, 2)


def log(day_offset: int, meal="lunch", calories=500, protein=20.0, source="manual", hour=12):
    d = TODAY - timedelta(days=day_offset)
    return LogRow(d, meal, source, calories, protein, datetime(d.year, d.month, d.day, hour))


def days(*offsets, **kw):
    return [log(o, **kw) for o in offsets]


def progress(rows, calorie_target=2000, protein_target=120, today=TODAY):
    return compute_progress(rows, today, calorie_target, protein_target)


def achievement(p, achievement_id):
    return next(a for a in p["achievements"] if a["id"] == achievement_id)


# --- streaks -----------------------------------------------------------------


def test_no_logs_is_an_empty_but_valid_state():
    p = progress([])
    assert p["streak"]["current"] == 0
    assert p["streak"]["tier"] == "spark"
    assert p["level"] == {"level": 1, "xp": 0, "level_xp": 0, "next_level_xp": 100}
    assert not any(a["unlocked"] for a in p["achievements"])


def test_consecutive_days_build_a_streak():
    p = progress(days(0, 1, 2, 3))
    assert p["streak"]["current"] == 4
    assert p["streak"]["tier"] == "ember"
    assert p["streak"]["logged_today"] is True


def test_not_logging_today_yet_keeps_yesterdays_streak_alive():
    p = progress(days(1, 2, 3))
    assert p["streak"]["current"] == 3
    assert p["streak"]["logged_today"] is False


def test_a_missed_day_without_a_freeze_resets_the_streak():
    p = progress(days(0, 2, 3, 4))  # day 1 missed, no freeze earned yet
    assert p["streak"]["current"] == 1
    assert p["streak"]["best"] == 3


def test_a_freeze_is_earned_every_7_days_and_saves_a_missed_day():
    rows = days(*range(2, 9))  # 7 days, ending the day before yesterday
    rows += days(0)  # yesterday (offset 1) missed, logged today
    p = progress(rows)
    assert p["streak"]["current"] == 8  # 7 + today; the gap was frozen
    assert p["streak"]["freezes"] == 0  # the one earned was spent
    assert p["streak"]["frozen_days"] == [TODAY - timedelta(days=1)]


def test_freezes_cap_at_the_maximum():
    p = progress(days(*range(0, 35)))
    assert p["streak"]["freezes"] == MAX_FREEZES


def test_two_missed_days_with_one_freeze_still_reset():
    rows = days(*range(3, 10)) + days(0)  # 7 days, then days 1 and 2 missed
    p = progress(rows)
    assert p["streak"]["current"] == 1


def test_logs_dated_after_today_are_ignored():
    rows = days(0) + [log(-1)]  # another device already on tomorrow
    assert progress(rows)["streak"]["current"] == 1


def test_tiers():
    assert [tier_for(n) for n in (0, 2, 3, 7, 14, 30, 365)] == [
        "spark", "spark", "ember", "flame", "blaze", "inferno", "inferno",
    ]


# --- XP and levels -----------------------------------------------------------


def test_level_curve():
    assert [xp_for_level(n) for n in (1, 2, 3, 4, 5)] == [0, 100, 300, 600, 1000]
    assert level_for(0) == 1
    assert level_for(99) == 1
    assert level_for(100) == 2
    assert level_for(299) == 2
    assert level_for(1000) == 5


def test_xp_for_a_single_plain_entry():
    # 10 per entry + streak bonus 2 x 1 day; 500 kcal is not a perfect day
    assert progress(days(0))["level"]["xp"] == 12


def test_entry_xp_is_capped_so_tiny_logs_cannot_farm_it():
    rows = [log(0, calories=10, protein=0) for _ in range(20)]
    assert progress(rows)["level"]["xp"] == 10 * 6 + 2


def test_photo_full_house_protein_and_perfect_day_bonuses():
    rows = [
        log(0, "breakfast", 500, 30, source="photo"),
        log(0, "lunch", 600, 40),
        log(0, "dinner", 700, 45),
        log(0, "snack", 200, 10),
    ]  # 2000 kcal = perfect; 125 g protein >= 120
    p = progress(rows)
    # entries 40 + photo 5 + full house 20 + protein 20 + perfect 30 + streak 2
    assert p["level"]["xp"] == 117
    assert p["today"]["perfect_day"] is True
    assert p["today"]["xp"] == 117


def test_eating_far_less_than_the_target_earns_no_perfect_day():
    """Never reward a deficit: 900 of 2000 kcal is not a "perfect" day."""
    p = progress(days(0, calories=900))
    assert p["today"]["perfect_day"] is False
    assert p["today"]["target_low"] == 1800
    assert p["today"]["target_high"] == 2200
    assert achievement(p, "bullseye")["unlocked"] is False


def test_overshooting_the_band_is_not_perfect_either():
    assert progress(days(0, calories=2300))["today"]["perfect_day"] is False


def test_no_target_means_no_perfect_day_or_protein_bonus():
    p = progress(days(0, calories=2000, protein=500), calorie_target=None, protein_target=None)
    assert p["today"]["perfect_day"] is False
    assert p["today"]["target_low"] is None
    assert p["level"]["xp"] == 12


# --- achievements ------------------------------------------------------------


def test_simple_achievements_unlock_on_the_day_they_happen():
    rows = [
        log(3, "breakfast", hour=7),  # early bird
        log(2, source="photo"),       # snapshot
    ]
    p = progress(rows)
    assert achievement(p, "first_bite")["unlocked_on"] == TODAY - timedelta(days=3)
    assert achievement(p, "early_bird")["unlocked_on"] == TODAY - timedelta(days=3)
    assert achievement(p, "snapshot")["unlocked_on"] == TODAY - timedelta(days=2)
    assert achievement(p, "full_house")["unlocked"] is False


def test_late_breakfast_is_not_an_early_bird():
    assert achievement(progress(days(0, meal="breakfast", hour=10)), "early_bird")["unlocked"] is False


def test_protein_pro_needs_five_days_in_a_row_and_reports_progress():
    rows = days(0, 1, 2, protein=130) + days(3, protein=10) + days(4, 5, 6, 7, protein=130)
    p = progress(rows)
    pro = achievement(p, "protein_pro")
    assert pro["unlocked"] is False
    assert pro["progress"] == 4  # best run so far
    assert pro["goal"] == 5

    p = progress(days(0, 1, 2, 3, 4, protein=130))
    assert achievement(p, "protein_pro")["unlocked"] is True


def test_streak_achievements_keep_counting_after_a_break():
    rows = days(*range(10, 17)) + days(0)  # a 7-day streak last week, broken
    p = progress(rows)
    assert p["streak"]["current"] == 1
    assert achievement(p, "on_fire")["unlocked"] is True
    assert achievement(p, "inferno")["progress"] == 7


def test_centurion_progress_is_capped_at_the_goal():
    rows = [log(0) for _ in range(120)]
    p = progress(rows)
    assert achievement(p, "centurion")["progress"] == 100
    assert achievement(p, "centurion")["unlocked"] is True


# --- endpoint ----------------------------------------------------------------


def test_progress_endpoint_requires_auth(anon_client):
    assert anon_client.get("/progress").status_code == 401


def test_progress_endpoint_scores_the_users_logs(client, monkeypatch):
    from app.core.database import get_db
    from app.main import app
    from app.routers import progress as progress_router

    seen = {}

    def fixed_today(client_date):
        seen["client_date"] = client_date
        return TODAY

    monkeypatch.setattr(progress_router, "resolve_today", fixed_today)

    log_rows = [(TODAY, "breakfast", "photo", 2000, 130.0, datetime(2026, 11, 2, 7))]

    class _Result:
        def __init__(self, data):
            self.data = data

        def all(self):
            return self.data

        def first(self):
            return self.data[0] if self.data else None

    class FakeDb:
        def __init__(self):
            self.calls = 0

        async def execute(self, _stmt):
            self.calls += 1
            return _Result(log_rows) if self.calls == 1 else _Result([(2000, 120)])

    async def fake_db():
        yield FakeDb()

    app.dependency_overrides[get_db] = fake_db
    r = client.get("/progress", params={"date": "2026-11-02"})

    assert r.status_code == 200
    assert seen["client_date"] == TODAY
    body = r.json()
    assert body["date"] == "2026-11-02"
    assert body["streak"]["current"] == 1
    assert body["today"]["perfect_day"] is True
    assert achievement(body, "early_bird")["unlocked"] is True
    assert achievement(body, "snapshot")["unlocked"] is True
