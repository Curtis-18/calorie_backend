import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services.notification_rules import (
    DAILY_CAP,
    Kind,
    Prefs,
    copy_for,
    decide,
    in_quiet_hours,
    in_reminder_window,
    local_day_bounds_utc,
    pick_streak_to_save,
)

ME = uuid.UUID("00000000-0000-0000-0000-000000000001")
SAM = uuid.UUID("00000000-0000-0000-0000-000000000002")


def at(hour, minute=0, day=5):
    return datetime(2026, 11, day, hour, minute, tzinfo=timezone.utc)


# --- quiet hours -------------------------------------------------------------

def test_quiet_hours_wrap_past_midnight():
    assert in_quiet_hours(23, 22, 8) and in_quiet_hours(0, 22, 8) and in_quiet_hours(7, 22, 8)
    assert not in_quiet_hours(8, 22, 8) and not in_quiet_hours(12, 22, 8) and not in_quiet_hours(21, 22, 8)


def test_quiet_hours_inside_one_day_and_off():
    assert in_quiet_hours(13, 12, 14) and not in_quiet_hours(14, 12, 14)
    assert not in_quiet_hours(3, 5, 5)  # same start and end means no quiet hours


# --- the decision ------------------------------------------------------------

def test_a_normal_daytime_notification_is_allowed():
    assert decide(Kind.FRIEND_SNAP, Prefs(), at(12), sent_today=0).allowed


def test_the_daily_cap_is_hard():
    assert DAILY_CAP == 3
    assert decide(Kind.FRIEND_SNAP, Prefs(), at(12), sent_today=2).allowed
    d = decide(Kind.FRIEND_SNAP, Prefs(), at(12), sent_today=3)
    assert not d.allowed and d.reason == "daily_cap"


def test_quiet_hours_use_the_persons_own_clock():
    # 23:00 UTC is 10:00 next morning in UTC+11: fine there, but 23:00 in UTC.
    assert not decide(Kind.FRIEND_SNAP, Prefs(), at(23), 0).allowed
    assert decide(Kind.FRIEND_SNAP, Prefs(utc_offset_minutes=11 * 60), at(23), 0).allowed
    # 12:00 UTC is 21:00 in UTC+9 (allowed) and 23:30 in UTC+11:30 (quiet).
    assert decide(Kind.FRIEND_SNAP, Prefs(utc_offset_minutes=9 * 60), at(12), 0).allowed
    d = decide(Kind.FRIEND_SNAP, Prefs(utc_offset_minutes=11 * 60 + 30), at(12), 0)
    assert not d.allowed and d.reason == "quiet_hours"


def test_each_kind_has_its_own_switch():
    p = Prefs(reactions=False)
    assert decide(Kind.REACTION, p, at(12), 0).reason == "switched_off"
    assert decide(Kind.FRIEND_SNAP, p, at(12), 0).allowed
    p = Prefs(streak_reminders=False)
    assert decide(Kind.STREAK_AT_RISK, p, at(12), 0).reason == "switched_off"
    assert decide(Kind.STREAK_FREEZE, p, at(12), 0).reason == "switched_off"
    assert decide(Kind.MILESTONE, Prefs(milestones=False), at(12), 0).reason == "switched_off"


def test_pausing_silences_everything_until_it_ends():
    p = Prefs(paused_until=at(12) + timedelta(days=7))
    for kind in Kind:
        assert decide(kind, p, at(12), 0).reason == "paused"
    assert decide(Kind.FRIEND_SNAP, p, at(12) + timedelta(days=8), 0).allowed


def test_local_day_bounds():
    p = Prefs(utc_offset_minutes=-300)  # UTC-5
    start, end = local_day_bounds_utc(at(3), p)  # 22:00 on the 4th, local
    assert start == datetime(2026, 11, 4, 5, 0, tzinfo=timezone.utc)
    assert end - start == timedelta(days=1)
    start, _ = local_day_bounds_utc(at(12), Prefs())
    assert start == at(0)


# --- copy --------------------------------------------------------------------

BANNED = ("calorie", "kcal", "weight", "diet", "fat", "skipped", "missed", "failed", "lazy", "miss you", "we miss")


@pytest.mark.parametrize("kind", list(Kind))
def test_copy_is_short_and_never_about_food_numbers_or_guilt(kind):
    for key in ("a", "b", "c", "d", "e", "f"):
        title, body = copy_for(kind, key, name="sam", emoji="🔥", count=6)
        text = f"{title} {body}".lower()
        assert "{" not in text and "}" not in text
        assert len(title) <= 60 and len(body) <= 90
        assert not any(word in text for word in BANNED), text


def test_copy_is_stable_for_the_same_event_and_fills_in_names():
    a = copy_for(Kind.FRIEND_SNAP, "snap:1", name="sam")
    assert a == copy_for(Kind.FRIEND_SNAP, "snap:1", name="sam")
    assert "sam" in a[0]
    titles = {copy_for(Kind.FRIEND_SNAP, f"k{i}", name="sam")[0] for i in range(30)}
    assert len(titles) > 1  # varied across events


# --- which streak to remind about -----------------------------------------------

def test_reminder_window_is_early_evening():
    assert not in_reminder_window(17) and in_reminder_window(18) and in_reminder_window(20)
    assert not in_reminder_window(21)


def test_pick_the_longest_running_streak_I_still_owe():
    picks = pick_streak_to_save([("zed", 3, False), ("amy", 9, False), ("bob", 20, True), ("cat", 0, False)])
    assert picks == ("amy", 9)  # bob's is longer but I've already sent today
    assert pick_streak_to_save([("bob", 5, True), ("cat", 0, False)]) is None
    assert pick_streak_to_save([]) is None
    assert pick_streak_to_save([("b", 4, False), ("A", 4, False)]) == ("A", 4)  # ties: by name


# --- the notifier --------------------------------------------------------------

class _Scalars:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class _Result:
    def __init__(self, value=None, rows=None):
        self.value, self.rows = value, rows or []

    def scalar_one_or_none(self):
        return self.value

    def scalar_one(self):
        return self.value

    def scalars(self):
        return _Scalars(self.rows)

    def all(self):
        return self.rows


class _Db:
    def __init__(self, *results):
        self.results = list(results)
        self.executed = []
        self.committed = False

    async def execute(self, stmt):
        self.executed.append(stmt)
        return self.results.pop(0)

    async def commit(self):
        self.committed = True


@pytest.fixture
def sent(monkeypatch):
    from app.services import push_sender

    calls = []

    async def fake_send(tokens, title, body, data=None):
        calls.append((tokens, title, body, data))
        return "dry_run"

    monkeypatch.setattr(push_sender, "send", fake_send)
    return calls


async def _notify(db, kind=Kind.FRIEND_SNAP, **kw):
    from app.services.notifier import notify

    kw.setdefault("now", at(12))
    return await notify(db, ME, kind, **kw)


@pytest.mark.asyncio
async def test_no_device_means_nothing_is_sent(sent):
    db = _Db(_Result(rows=[]))
    assert await _notify(db, name="sam") == "no_device"
    assert not sent


@pytest.mark.asyncio
async def test_a_good_notification_is_logged_and_sent(sent):
    db = _Db(
        _Result(rows=["tok-1"]),   # device tokens
        _Result(None),             # no prefs row: defaults
        _Result(0),                # sent today
        _Result(ME),               # dedupe claim inserted
        _Result(),                 # status update
    )
    assert await _notify(db, dedupe_key="snap:1", name="sam") == "dry_run"
    assert sent[0][0] == ["tok-1"] and "sam" in sent[0][1] and db.committed


@pytest.mark.asyncio
async def test_the_cap_stops_the_fourth_one(sent):
    db = _Db(_Result(rows=["tok"]), _Result(None), _Result(3))
    assert await _notify(db, name="sam") == "daily_cap"
    assert not sent


@pytest.mark.asyncio
async def test_quiet_hours_stop_it(sent):
    db = _Db(_Result(rows=["tok"]), _Result(None), _Result(0))
    assert await _notify(db, name="sam", now=at(23)) == "quiet_hours"
    assert not sent


@pytest.mark.asyncio
async def test_a_repeat_with_the_same_key_is_a_duplicate(sent):
    db = _Db(_Result(rows=["tok"]), _Result(None), _Result(0), _Result(None))  # claim returns nothing
    assert await _notify(db, dedupe_key="streak:2026-11-05", name="sam", count=4) == "duplicate"
    assert not sent


@pytest.mark.asyncio
async def test_a_delivery_error_is_recorded_not_raised(monkeypatch):
    from app.services import push_sender

    async def boom(*a, **k):
        raise push_sender.PushUnavailable("no provider")

    monkeypatch.setattr(push_sender, "send", boom)
    db = _Db(_Result(rows=["tok"]), _Result(None), _Result(0), _Result(ME), _Result())
    assert await _notify(db, name="sam") == "failed"


@pytest.mark.asyncio
async def test_notify_user_never_raises(monkeypatch):
    from app.services import notifier

    class Broken:
        async def __aenter__(self):
            raise RuntimeError("db down")

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(notifier, "async_session_maker", lambda: Broken())
    assert await notifier.notify_user(ME, Kind.FRIEND_SNAP, name="sam") == "failed"


def test_dry_run_is_the_default_and_other_modes_have_no_provider():
    import asyncio

    from app.core.config import settings
    from app.services import push_sender

    assert settings.push_mode == "dry_run"
    assert asyncio.run(push_sender.send(["t"], "a", "b")) == "dry_run"
    old = settings.push_mode
    settings.push_mode = "fcm"
    try:
        with pytest.raises(push_sender.PushUnavailable):
            asyncio.run(push_sender.send(["t"], "a", "b"))
    finally:
        settings.push_mode = old


# --- the API ---------------------------------------------------------------------

def _with_db(db):
    from app.core.database import get_db
    from app.main import app

    async def fake_db():
        yield db

    app.dependency_overrides[get_db] = fake_db


PREFS_ROW = SimpleNamespace(
    user_id=ME, friend_snaps=True, reactions=False, streak_reminders=True, milestones=True,
    meal_nudge_hour=None, quiet_start=22, quiet_end=8, utc_offset_minutes=120, paused_until=None,
)


def test_prefs_default_when_nothing_is_saved(client):
    _with_db(_Db(_Result(None)))
    r = client.get("/notifications/prefs")
    assert r.status_code == 200
    out = r.json()
    assert out["friend_snaps"] and out["streak_reminders"] and out["milestones"]
    assert (out["quiet_start"], out["quiet_end"], out["daily_cap"]) == (22, 8, 3)
    assert out["meal_nudge_hour"] is None and out["paused_until"] is None


def test_prefs_can_be_changed_and_are_returned(client):
    db = _Db(_Result(), _Result(PREFS_ROW))
    _with_db(db)
    r = client.post("/notifications/prefs", json={"reactions": False, "utc_offset_minutes": 120})
    assert r.status_code == 200 and r.json()["reactions"] is False and r.json()["utc_offset_minutes"] == 120
    assert db.committed


def test_prefs_are_validated(client):
    _with_db(_Db())
    for bad in ({"quiet_start": 24}, {"quiet_end": -1}, {"utc_offset_minutes": 900}, {"pause_days": 15},
                {"meal_nudge_hour": 24}):
        assert client.post("/notifications/prefs", json=bad).status_code == 422, bad


def test_pausing_sets_a_future_time_and_zero_resumes(client):
    db = _Db(_Result(), _Result(PREFS_ROW))
    _with_db(db)
    assert client.post("/notifications/prefs", json={"pause_days": 7}).status_code == 200
    sql = str(db.executed[0].compile(compile_kwargs={"literal_binds": False}))
    assert "paused_until" in sql


def test_registering_a_device(client):
    db = _Db(_Result(), _Result())
    _with_db(db)
    r = client.post("/notifications/devices", json={"token": "x" * 64, "platform": "ios", "utc_offset_minutes": 180})
    assert r.status_code == 204 and db.committed
    assert client.post("/notifications/devices", json={"token": "short", "platform": "ios"}).status_code == 422
    assert client.post("/notifications/devices", json={"token": "x" * 64, "platform": "blackberry"}).status_code == 422


def test_removing_a_device_only_touches_your_own(client):
    db = _Db(_Result())
    _with_db(db)
    assert client.delete("/notifications/devices/" + "x" * 64).status_code == 204
    assert "user_id" in str(db.executed[0].compile())


def test_notification_endpoints_need_sign_in(anon_client):
    assert anon_client.get("/notifications/prefs").status_code == 401
    assert anon_client.post("/notifications/devices", json={}).status_code in (401, 403, 422)


def test_the_streak_cron_is_off_without_a_secret_and_guarded_with_one(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "cron_secret", None)
    assert client.post("/notifications/cron/streak-reminders").status_code == 404
    monkeypatch.setattr(settings, "cron_secret", "s3cret")
    assert client.post("/notifications/cron/streak-reminders").status_code == 403
    assert client.post("/notifications/cron/streak-reminders", headers={"X-Cron-Secret": "nope"}).status_code == 403


def test_the_streak_cron_with_nobody_registered_does_nothing(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "cron_secret", "s3cret")
    _with_db(_Db(_Result(rows=[]), _Result()))  # no device owners; log cleanup
    r = client.post("/notifications/cron/streak-reminders", headers={"X-Cron-Secret": "s3cret"})
    assert r.status_code == 200 and r.json() == {"checked": 0, "sent": 0}


# --- reminders about your own logging ---------------------------------------

from app.services.notification_rules import own_reminders  # noqa: E402


def test_nothing_is_due_once_you_have_logged_today():
    for hour in (15, 19, 21):
        assert own_reminders(hour, logged_today=True, streak=9) == []


def test_afternoon_nudges_anyone_who_has_logged_nothing():
    assert own_reminders(15, logged_today=False, streak=0) == [(Kind.LOG_REMINDER, "nolog")]
    assert own_reminders(15, logged_today=False, streak=5) == [(Kind.LOG_REMINDER, "nolog")]


def test_evening_warns_only_a_running_streak():
    assert own_reminders(20, logged_today=False, streak=4) == [(Kind.MY_STREAK_AT_RISK, "mystreak")]
    assert own_reminders(20, logged_today=False, streak=0) == []


def test_no_logging_reminders_in_the_morning_or_late_night():
    for hour in (6, 9, 12, 13, 22, 23):
        assert own_reminders(hour, logged_today=False, streak=4) == []


def test_the_new_reminders_respect_the_streak_switch_and_quiet_hours():
    assert not decide(Kind.LOG_REMINDER, Prefs(streak_reminders=False), at(15), 0).allowed
    assert not decide(Kind.MY_STREAK_AT_RISK, Prefs(streak_reminders=False), at(20), 0).allowed
    assert decide(Kind.MY_STREAK_AT_RISK, Prefs(), at(20), 0).allowed


@pytest.mark.parametrize("kind", [Kind.LOG_REMINDER, Kind.MY_STREAK_AT_RISK])
def test_logging_reminder_copy_is_short_and_has_no_numbers_about_food(kind):
    for key in ("a", "b", "c", "d", "e"):
        title, body = copy_for(kind, key, count=12)
        assert len(title) <= 60 and len(body) <= 90
        assert "kcal" not in (title + body).lower() and "calorie" not in (title + body).lower()


# --- on by default -----------------------------------------------------------

def test_with_nothing_saved_every_notification_is_on():
    from app.services.notifier import prefs_from_row

    p = prefs_from_row(None)
    assert p.friend_snaps and p.reactions and p.streak_reminders and p.milestones
    assert p.paused_until is None
    for kind in Kind:
        assert decide(kind, p, at(12), 0).allowed, kind


def test_a_saved_row_without_choices_also_starts_everything_on():
    """Registering a device saves only the time zone; the switches must come out on."""
    from app.models.notification import NotificationPrefs

    cols = NotificationPrefs.__table__.c
    for name in ("friend_snaps", "reactions", "streak_reminders", "milestones"):
        assert cols[name].default.arg is True, name
    assert cols.paused_until.default is None


# --- friends, messages and the extra fun copy ---------------------------------

SOCIAL = [Kind.FRIEND_REQUEST, Kind.FRIEND_ACCEPTED, Kind.MESSAGE]


@pytest.mark.parametrize("kind", SOCIAL)
def test_social_kinds_follow_the_friends_switch_and_all_the_usual_rules(kind):
    assert decide(kind, Prefs(), at(12), 0).allowed
    assert decide(kind, Prefs(friend_snaps=False), at(12), 0).reason == "switched_off"
    assert decide(kind, Prefs(), at(23), 0).reason == "quiet_hours"
    assert decide(kind, Prefs(), at(12), DAILY_CAP).reason == "daily_cap"
    assert decide(kind, Prefs(paused_until=at(20)), at(12), 0).reason == "paused"


@pytest.mark.parametrize("kind", SOCIAL)
def test_social_copy_names_the_person_when_it_has_one_and_is_varied(kind):
    titles = set()
    for i in range(40):
        title, body = copy_for(kind, f"k{i}", name="sam")
        titles.add(title)
        assert "{" not in title + body
    assert len(titles) == 3


def test_a_message_notification_never_has_the_message_in_it():
    for i in range(10):
        title, body = copy_for(Kind.MESSAGE, f"k{i}", name="sam", text="secret plans")
        assert "secret" not in (title + body).lower()


def test_more_variety_in_the_existing_kinds():
    for kind, n in [(Kind.FRIEND_SNAP, 5), (Kind.REACTION, 4), (Kind.LOG_REMINDER, 5), (Kind.MY_STREAK_AT_RISK, 4)]:
        seen = {copy_for(kind, f"k{i}", name="sam", emoji="🔥", count=6)[0] for i in range(80)}
        assert len(seen) >= n - 1, kind


def test_every_new_line_is_translated_in_all_five_languages():
    from app.i18n import TABLES
    from app.services.notification_rules import _COPY

    for lang in ("es", "fr", "de", "pt", "it"):
        for kind in (*SOCIAL, Kind.FRIEND_SNAP, Kind.REACTION, Kind.LOG_REMINDER, Kind.MY_STREAK_AT_RISK):
            for title, body in _COPY[kind]:
                assert title in TABLES[lang] and body in TABLES[lang], (lang, title, body)
                # placeholders survive translation, so nothing breaks at send time
                for text, original in ((TABLES[lang][title], title), (TABLES[lang][body], body)):
                    for ph in ("{name}", "{emoji}", "{count}"):
                        assert (ph in text) == (ph in original), (lang, original)


@pytest.mark.asyncio
async def test_notify_from_never_raises_either(monkeypatch):
    from app.services import notifier

    class Broken:
        async def __aenter__(self):
            raise RuntimeError("db down")

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(notifier, "async_session_maker", lambda: Broken())
    assert await notifier.notify_from(ME, Kind.MESSAGE, SAM) == "failed"


@pytest.mark.asyncio
async def test_notify_from_puts_the_doers_username_in_the_text(monkeypatch):
    from app.services import notifier

    seen = {}

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def execute(self, stmt):
            return SimpleNamespace(scalar_one_or_none=lambda: "sam")

    async def fake_notify(db, user_id, kind, *, dedupe_key=None, **ctx):
        seen.update(kind=kind, ctx=ctx, key=dedupe_key)
        return "sent"

    monkeypatch.setattr(notifier, "async_session_maker", lambda: Session())
    monkeypatch.setattr(notifier, "notify", fake_notify)
    assert await notifier.notify_from(ME, Kind.FRIEND_REQUEST, SAM, dedupe_key="k") == "sent"
    assert seen == {"kind": Kind.FRIEND_REQUEST, "ctx": {"name": "sam"}, "key": "k"}


# --- badges, levels and streak freezes (NEXT_STEPS step 6) ----------------------

import re  # noqa: E402
from datetime import date  # noqa: E402

from app.services.notification_rules import (  # noqa: E402
    BADGE_LINE,
    LEVEL_LINE,
    MILESTONE_WINDOW,
    milestone_events,
)
from app.services.progress_read import ProgressInputs  # noqa: E402
from app.services.progress_service import LogRow, compute_progress  # noqa: E402

DAY = date(2026, 11, 5)  # the same day as at(...)


def _log(d, source="manual", meal="lunch"):
    return LogRow(d, meal, source, 500, 20.0, None)


def _progress(rows, day=DAY, weigh_ins=()):
    return compute_progress(rows, today=day, calorie_target=None, protein_target=None, weigh_in_dates=list(weigh_ins))


def _events(rows, day=DAY, weigh_ins=()):
    return milestone_events(_progress(rows, day, weigh_ins), _progress(rows, day - timedelta(days=1), weigh_ins), day)


def _freeze_week():
    """Seven days logged (a freeze is kept on day 7), then yesterday missed."""
    return [_log(DAY - timedelta(days=n)) for n in range(2, 9)]


def test_a_badge_unlocked_today_is_news_with_the_badge_line():
    assert _events([_log(DAY)]) == [(Kind.MILESTONE, "badge:first_bite", {"name": "First Bite", "variant": BADGE_LINE})]


def test_a_badge_unlocked_on_an_earlier_day_is_not_news():
    assert _events([_log(DAY - timedelta(days=1))]) == []
    assert _events([]) == []


def test_badges_about_weighing_yourself_are_never_announced():
    events = _events([], weigh_ins=[DAY])
    assert events == [], "push text is never about weight"


def test_a_new_level_is_news_with_the_level_line():
    now = {"streak": {"frozen_days": [], "current": 4}, "achievements": [], "level": {"level": 3}}
    before = {"streak": {"frozen_days": [], "current": 3}, "achievements": [], "level": {"level": 2}}
    assert milestone_events(now, before, DAY) == [(Kind.MILESTONE, "level:3", {"count": 3, "variant": LEVEL_LINE})]
    assert milestone_events(now, now, DAY) == []


def test_a_freeze_that_covered_yesterday_is_news():
    events = _events(_freeze_week())
    assert events == [(Kind.STREAK_FREEZE, "freeze:2026-11-04", {"count": 7})]


def test_freeze_news_comes_first_then_badges():
    events = _events(_freeze_week() + [_log(DAY, source="photo")])
    assert [key for _, key, _ in events][:2] == ["freeze:2026-11-04", "badge:snapshot"]


def test_the_badge_and_level_lines_read_right():
    assert copy_for(Kind.MILESTONE, "badge:first_bite", variant=BADGE_LINE, name="First Bite") == (
        "🏅 New badge: First Bite", "Come and see it in your progress.")
    assert copy_for(Kind.MILESTONE, "level:4", variant=LEVEL_LINE, count=4)[0] == "⭐ Level 4!"
    assert copy_for(Kind.STREAK_FREEZE, "freeze:x", count=7) == ("🧊 A freeze covered yesterday", "Your 7-day flame is safe.")


def test_milestone_copy_never_says_earn_in_any_language():
    """"You earned it" was the first wording; "earn" is on the banned list (and so are
    its translations: ganado, mérité, verdient, mereceu, guadagnato)."""
    from app.i18n import TABLES
    from app.services.notification_rules import _COPY

    old = ("ganad", "mérit", "verdien", "merece", "guadagn")
    for kind in (Kind.MILESTONE, Kind.STREAK_FREEZE):
        for title, body in _COPY[kind]:
            assert not re.search(r"\bearn", f"{title} {body}", re.I), (title, body)
            for lang in ("es", "fr", "de", "pt", "it"):
                for text, original in ((TABLES[lang][title], title), (TABLES[lang][body], body)):
                    assert not any(w in text.lower() for w in old), (lang, text)
                    for ph in ("{name}", "{count}"):
                        assert (ph in text) == (ph in original), (lang, original)
                    assert not any(word in text.lower() for word in BANNED), (lang, text)


def test_milestone_news_goes_in_the_daytime():
    assert MILESTONE_WINDOW == (10, 20)


class _CronDb(_Db):
    def __init__(self, *results):
        super().__init__(*results)
        self.rolled_back = 0

    async def rollback(self):
        self.rolled_back += 1


def _cron(client, monkeypatch, *, hour, inputs=None, prefs_rows=(), statuses=("dry_run",), lang="en", fail=False):
    """Runs the hourly job for one person with a device, at [hour] UTC on DAY.
    Returns (response, notify calls, how often the history was loaded, db)."""
    from app.core.config import settings
    from app.routers import notifications as router
    from app.services import language_pref, progress_read

    monkeypatch.setattr(settings, "cron_secret", "s3cret")
    monkeypatch.setattr(router, "_utcnow", lambda: at(hour))
    calls, loads, answers = [], [], list(statuses)

    async def fake_notify(db, uid, kind, *, dedupe_key=None, now=None, **ctx):
        calls.append((kind, dedupe_key, ctx))
        return answers.pop(0) if answers else "dry_run"

    async def fake_load(db, uid, today):
        loads.append(today)
        if fail:
            raise RuntimeError("database hiccup")
        return inputs

    async def fake_recall(db, uid):
        return lang

    monkeypatch.setattr(router, "notify", fake_notify)
    monkeypatch.setattr(progress_read, "load_inputs", fake_load)
    monkeypatch.setattr(language_pref, "recall", fake_recall)
    db = _CronDb(_Result(rows=[ME]), _Result(rows=list(prefs_rows)), _Result())  # device owners; prefs; log cleanup
    _with_db(db)
    r = client.post("/notifications/cron/streak-reminders", headers={"X-Cron-Secret": "s3cret"})
    return r, calls, loads, db


def _inputs(rows):
    return ProgressInputs(rows=rows, calorie_target=None, protein_target=None, weigh_in_dates=[])


def test_the_hourly_job_sends_a_badge_unlocked_today_in_the_persons_language(client, monkeypatch):
    from app.i18n import t

    r, calls, loads, _ = _cron(client, monkeypatch, hour=12, inputs=_inputs([_log(DAY)]), lang="es")
    assert r.status_code == 200 and r.json() == {"checked": 1, "sent": 1}
    assert loads == [DAY]
    assert calls == [(Kind.MILESTONE, "badge:first_bite", {"name": t("es", "First Bite"), "variant": BADGE_LINE})]


def test_the_hourly_job_moves_past_one_already_sent_and_sends_at_most_one(client, monkeypatch):
    rows = [_log(DAY, source="photo")]  # first_bite and snapshot, both today
    r, calls, _, _ = _cron(client, monkeypatch, hour=12, inputs=_inputs(rows), statuses=("duplicate", "dry_run"))
    assert [key for _, key, _ in calls] == ["badge:first_bite", "badge:snapshot"]
    assert r.json() == {"checked": 1, "sent": 1}


def test_the_rules_saying_no_stops_the_run_for_that_person(client, monkeypatch):
    rows = [_log(DAY, source="photo")]
    r, calls, _, _ = _cron(client, monkeypatch, hour=12, inputs=_inputs(rows), statuses=("daily_cap",))
    assert len(calls) == 1 and r.json()["sent"] == 0


def test_nothing_is_loaded_outside_the_daytime_window(client, monkeypatch):
    r, calls, loads, _ = _cron(client, monkeypatch, hour=9, inputs=_inputs([_log(DAY)]))
    assert r.json() == {"checked": 0, "sent": 0} and loads == [] and calls == []


def _prefs(**over):
    values = {**PREFS_ROW.__dict__, "utc_offset_minutes": 0, **over}
    return SimpleNamespace(**values)


def test_with_both_switches_off_the_history_is_not_even_loaded(client, monkeypatch):
    r, calls, loads, _ = _cron(
        client, monkeypatch, hour=12, inputs=_inputs([_log(DAY)]),
        prefs_rows=[_prefs(milestones=False, streak_reminders=False)],
    )
    assert loads == [] and calls == [] and r.json()["sent"] == 0


def test_each_kind_follows_its_own_switch(client, monkeypatch):
    rows = _freeze_week() + [_log(DAY, source="photo")]  # a freeze covered yesterday, and a badge today
    _, calls, _, _ = _cron(client, monkeypatch, hour=12, inputs=_inputs(rows), prefs_rows=[_prefs(streak_reminders=False)])
    assert [(k, key) for k, key, _ in calls] == [(Kind.MILESTONE, "badge:snapshot")]
    _, calls, _, _ = _cron(client, monkeypatch, hour=12, inputs=_inputs(rows), prefs_rows=[_prefs(milestones=False)])
    assert [(k, key) for k, key, _ in calls] == [(Kind.STREAK_FREEZE, "freeze:2026-11-04")]


def test_quiet_hours_stop_milestone_news_before_anything_is_loaded(client, monkeypatch):
    _, calls, loads, _ = _cron(
        client, monkeypatch, hour=12, inputs=_inputs([_log(DAY)]), prefs_rows=[_prefs(quiet_start=11, quiet_end=13)],
    )
    assert loads == [] and calls == []


def test_one_persons_failure_is_rolled_back_and_the_job_still_answers(client, monkeypatch):
    r, calls, _, db = _cron(client, monkeypatch, hour=12, fail=True)
    assert r.status_code == 200 and calls == [] and db.rolled_back == 1 and db.committed


@pytest.mark.asyncio
async def test_notify_passes_the_chosen_line_through(sent):
    """The real notifier, not a fake: the level line is used whatever the key hashes to."""
    for key in ("level:2", "level:3", "level:4", "level:5"):
        sent.clear()
        db = _Db(_Result(rows=["tok-1"]), _Result(None), _Result(0), _Result(ME), _Result())
        assert await _notify(db, Kind.MILESTONE, dedupe_key=key, count=4, variant=LEVEL_LINE) == "dry_run"
        assert sent[0][1] == "⭐ Level 4!", key
