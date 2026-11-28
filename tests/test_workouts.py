"""R8.4 step 4c: curated bodyweight routines the coach may offer."""

import re
import uuid

import pytest

from app.i18n import SUPPORTED, TABLES
from app.services import coach_prompt, workouts
from app.services.coach_prompt import build_context, reply_problem, system_prompt
from tests.test_coach import send, setup  # noqa: F401  (the coach route fixtures)

OTHER = [c for c in SUPPORTED if c != "en"]


# ---- the library itself ---------------------------------------------------------------------------

def test_there_are_routines_from_two_to_thirty_minutes():
    assert {r.minutes for r in workouts.ROUTINES} == {2, 3, 5, 10, 15, 20, 30}
    # The coach's original seven are all still there.
    assert {"reset_5", "legs_5", "full_15", "core_15", "walk_15", "strength_30", "walk_30"} <= {r.id for r in workouts.ROUTINES}
    assert len({r.id for r in workouts.ROUTINES}) == len(workouts.ROUTINES)
    assert {r.focus for r in workouts.ROUTINES} <= set(workouts.FOCUS_LABELS)
    assert {r.level for r in workouts.ROUTINES} <= set(workouts.LEVEL_LABELS)
    assert set(workouts.FOCUS_SLICE) == set(workouts.FOCUS_LABELS) and set(workouts.FOCUS_SLICE.values()) == set(workouts.SLICES)


def test_every_step_uses_a_known_move_and_amount():
    for r in workouts.ROUTINES:
        for step in (*r.warm, *r.main, *r.cool):
            assert step.exercise in workouts.EXERCISES and step.kind in workouts.AMOUNTS and step.n > 0, r.id
        assert r.warm and r.main and r.cool and r.rounds >= 1, r.id


@pytest.mark.parametrize("routine", workouts.ROUTINES, ids=lambda r: r.id)
def test_the_stated_minutes_are_honest(routine):
    estimate = workouts.estimated_seconds(routine)
    assert abs(estimate - routine.minutes * 60) <= max(90, 0.2 * routine.minutes * 60), (routine.id, estimate)


def test_nothing_in_the_library_talks_about_calories_burning_or_earning_food():
    """R2.3: movement is never a punishment or a payment for food, and never given a calorie figure."""
    for phrase in workouts.every_phrase():
        assert reply_problem(phrase, 1200) is None, phrase
        assert not re.search(r"kcal|calor|burn|earn|diet|weight loss|fat loss|pizza|cheat|guilt", phrase, re.I), phrase


def test_the_safety_line_is_on_every_routine_in_every_language():
    for lang in SUPPORTED:
        for r in workouts.ROUTINES:
            shown = workouts.render(r, lang)
            assert shown["safety"] == workouts.t(lang, workouts.SAFETY) and "doctor" in workouts.SAFETY
            assert [s["title"] for s in shown["sections"]] == [
                workouts.t(lang, "Warm-up"), workouts.t(lang, "Main moves"), workouts.t(lang, "Cool-down")
            ]


def test_a_rendered_routine_repeats_only_when_it_has_rounds():
    reset = workouts.render(workouts.get("reset_5"))
    assert [s["repeat"] for s in reset["sections"]] == [None, None, None]
    full = workouts.render(workouts.get("full_15"))
    assert full["sections"][1]["repeat"] == "Repeat the main moves 3 times, resting a little between."
    assert full["duration"] == "15 minutes" and full["focus"] == "Strength"
    first = full["sections"][1]["steps"][0]
    assert first == {
        "name": "Bodyweight squat",
        "cue": "Sit your hips back as if onto a chair, keep your chest up, then stand.",
        "amount": "10 reps",
    }
    assert workouts.get("nope") is None


# ---- translations (the phrases go through t() by variable, so the scanning test cannot see them) --------

def test_every_phrase_the_library_can_send_is_translated_everywhere():
    for lang in OTHER:
        missing = [p for p in workouts.every_phrase() if p not in TABLES[lang]]
        assert missing == [], (lang, missing[:3])
        for phrase in workouts.every_phrase():
            assert TABLES[lang][phrase].strip()


def test_a_routine_is_written_in_the_persons_language():
    es = workouts.render(workouts.get("walk_15"), "es")
    assert es["name"] == "Caminata de 15 minutos" and es["duration"] == "15 minutos"
    assert es["sections"][0]["steps"][0]["amount"] == "3 minutos"
    assert workouts.names("de")[0]["title"] == "5-Minuten-Reset"


# ---- what the coach is told, and what a reply may attach --------------------------------------------------

def test_the_context_lists_the_routines_by_name_and_the_prompt_forbids_inventing_exercises():
    ctx = build_context(
        goal="maintain", calorie_target=2000, floor=1500, protein_g=100, carbs_g=250, fat_g=70, today_entries=[],
        today_totals={"calories": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0}, allowance_today=None, week=[],
        region=None, recipes=[], routines=workouts.names("en"),
    )
    assert "Routines you can offer (curated, no equipment; use the exact name):" in ctx
    assert "- 15-minute walk (15 min, walk)" in ctx and "- 5-minute reset (5 min, mobility)" in ctx
    prompt = system_prompt(ctx, "en")
    for rule in ("exact name", "Never describe, list or invent exercises", "never say it burns anything", "short on time"):
        assert rule in prompt
    assert "Do not give workout plans" not in prompt  # replaced by the curated-routine rule


def test_a_reply_naming_a_routine_comes_with_the_whole_routine(client, setup):  # noqa: F811
    setup.gemini.replies = ["You're short on time, so try the 15-minute walk today. Easy start, easy finish."]
    body = send(client, "I only have 15 minutes").json()
    assert [w["id"] for w in body["workouts"]] == ["walk_15"]
    walk = body["workouts"][0]
    assert walk["name"] == "15-minute walk" and walk["duration"] == "15 minutes"
    assert [s["title"] for s in walk["sections"]] == ["Warm-up", "Main moves", "Cool-down"]
    assert "doctor" in walk["safety"]


def test_only_one_routine_is_attached_even_if_several_are_named(client, setup):  # noqa: F811
    setup.gemini.replies = ["Try the 5-minute reset, or the 15-minute walk, or the 30-minute walk."]
    body = send(client, "ideas?").json()
    assert [w["id"] for w in body["workouts"]] == ["reset_5"]  # the first one named


def test_a_made_up_routine_attaches_nothing(client, setup):  # noqa: F811
    setup.gemini.replies = ["Try my 45-minute power circuit with burpees."]
    assert send(client, "workout?").json()["workouts"] == []


def test_the_routine_comes_in_the_apps_language_and_is_found_by_its_local_name(client, setup):  # noqa: F811
    setup.gemini.replies = ["Prueba la Caminata de 15 minutos, suave al empezar."]
    body = send(client, "ejercicio?", lang="es").json()
    assert body["workouts"][0]["name"] == "Caminata de 15 minutos"
    assert body["workouts"][0]["sections"][0]["title"] == "Calentamiento"
    # The English name is not what a Spanish reply uses, so it is not matched.
    setup.gemini.replies = ["Try the 15-minute walk."]
    assert send(client, "ejercicio?", lang="es").json()["workouts"] == []


def test_fixed_replies_and_old_threads_never_carry_a_routine(client, setup):  # noqa: F811
    assert send(client, "I make myself sick after meals").json()["workouts"] == []
    setup.gemini.replies = ["Burn it off with the 15-minute walk!", "A walk can feel good: the 15-minute walk is easy."]
    assert send(client, "I ate a lot").json()["workouts"][0]["id"] == "walk_15"  # the acceptable second answer
    setup.gemini.replies = ["Do the 30-minute walk to detox.", "Detox with the 30-minute walk."]
    assert send(client, "how to lose 5 kg").json()["workouts"] == []  # the fixed fallback
    setup.gemini.replies = ["Try the 15-minute walk."]
    send(client, "move?")
    assert all(m["workouts"] == [] for m in client.get("/coach/messages").json()["messages"])


# ---- the Workouts tab: library, cards and the player's step list -------------------------------

def test_every_slice_of_the_plate_has_routines_and_there_are_move_bites():
    slices = {workouts.slice_of(r) for r in workouts.ROUTINES}
    assert slices == set(workouts.SLICES)
    assert sorted(r.minutes for r in workouts.ROUTINES if r.minutes <= 5)[0] == 2  # tiny ones exist
    for s in workouts.SLICES:
        assert sum(1 for r in workouts.ROUTINES if workouts.slice_of(r) == s) >= 3, s


def test_the_library_is_shortest_first_and_each_card_is_complete():
    lib = workouts.library("en")
    minutes = [c["minutes"] for c in lib["routines"]]
    assert minutes == sorted(minutes) and len(lib["routines"]) == len(workouts.ROUTINES)
    assert lib["slices"] == ["strength", "cardio", "mobility", "fun"]
    for c in lib["routines"]:
        assert set(c) == {"id", "name", "minutes", "focus", "slice", "level", "level_label", "summary"}
        assert c["slice"] in workouts.SLICES and c["level"] in workouts.LEVEL_LABELS


def test_the_library_is_in_the_persons_language():
    es = {c["id"]: c for c in workouts.library("es")["routines"]}
    assert es["walk_15"]["name"] != "15-minute walk" and es["walk_15"]["level_label"] == "Fácil"


@pytest.mark.parametrize("routine", workouts.ROUTINES, ids=lambda r: r.id)
def test_the_player_list_matches_the_routine(routine):
    steps = workouts.play_steps(routine)
    assert steps[0]["section"] == "warm" and steps[-1]["section"] == "cool"
    assert {s["mode"] for s in steps} <= {"timed", "reps", "rest"}
    for s in steps:
        if s["mode"] == "timed":
            assert s["seconds"] and s["seconds"] > 0 and s["reps"] is None
        elif s["mode"] == "reps":
            assert s["reps"] and s["reps"] > 0 and s["seconds"] is None
        else:
            assert s["seconds"] == workouts.REST_SECONDS_PER_ROUND
    rests = [s for s in steps if s["mode"] == "rest"]
    assert len(rests) == (routine.rounds if routine.rounds > 1 else 0)
    rounds_seen = sorted({s["round"] for s in steps if s["section"] == "main"})
    assert rounds_seen == list(range(1, routine.rounds + 1))


def test_each_side_becomes_two_timed_steps_and_reps_each_side_stays_one():
    steps = workouts.play_steps(workouts.get("stretch_10"))
    hamstring = [s for s in steps if s["name"] == "Hamstring stretch"]
    assert [(s["mode"], s["seconds"], s["side"]) for s in hamstring] == [("timed", 30, 1), ("timed", 30, 2)]
    reach = [s for s in steps if s["name"] == "Side reach"]
    assert [(s["mode"], s["reps"], s["side"]) for s in reach] == [("reps", 6, None)]
    assert reach[0]["amount"] == "6 reps each side"


def test_the_total_time_of_the_player_list_matches_the_stated_minutes():
    for r in workouts.ROUTINES:
        timed = sum(s["seconds"] or 0 for s in workouts.play_steps(r))
        reps = sum((s["reps"] or 0) * workouts.SECONDS_PER_REP * (2 if "each side" in s["amount"] else 1) for s in workouts.play_steps(r))
        assert abs(timed + reps - r.minutes * 60) <= max(90, 0.2 * r.minutes * 60), r.id


def test_rest_is_between_rounds_and_nothing_in_the_new_text_is_about_calories():
    steps = workouts.play_steps(workouts.get("full_15"))
    assert [s["name"] for s in steps if s["mode"] == "rest"] == ["Rest"] * 3
    for lang in SUPPORTED:
        for step in workouts.play_steps(workouts.get("cardio_20"), lang):
            assert not re.search(r"kcal|calor|burn|earn", f"{step['name']} {step['cue']}", re.I)


# ---- the routes -----------------------------------------------------------------------------------

def test_the_library_route_needs_a_login_and_lists_routines(client):
    from app.main import app

    r = client.get("/workouts")
    assert r.status_code == 200
    body = r.json()
    assert len(body["routines"]) == len(workouts.ROUTINES) and body["slices"] == list(workouts.SLICES)
    from fastapi.testclient import TestClient

    app.dependency_overrides.clear()
    assert TestClient(app).get("/workouts").status_code in (401, 403)


def test_one_workout_comes_with_its_player_steps_and_a_missing_one_is_404(client):
    r = client.get("/workouts/walk_10")
    assert r.status_code == 200
    body = r.json()
    assert body["minutes"] == 10 and body["slice"] == "cardio" and body["level_label"] == "Easy"
    assert [s["mode"] for s in body["play"]] == ["timed", "timed", "timed"]
    assert body["safety"] == workouts.t("en", workouts.SAFETY)
    assert client.get("/workouts/nope").status_code == 404


def test_the_route_speaks_the_language_in_the_header(client):
    r = client.get("/workouts/walk_10", headers={"Accept-Language": "es"})
    assert r.json()["name"] == "Caminata de 10 minutos"


# ---- "Easier version" in the player (NEXT_STEPS step 9a) ------------------------------------------

def test_every_easier_version_is_a_move_from_the_library():
    for move, (gentler, kind, share) in workouts.EASIER.items():
        assert move in workouts.EXERCISES and gentler in workouts.EXERCISES, move
        assert kind is None or kind in workouts.AMOUNTS
        assert 0 < share <= 1
        if gentler == move:
            assert share < 1, f"{move}: the same move must at least be shorter"


def test_the_easier_version_is_never_longer_than_the_usual_one():
    for r in workouts.ROUTINES:
        for step in (*r.warm, *r.main, *r.cool):
            gentler = workouts.easier_step(step)
            if gentler is None:
                continue
            assert gentler.n <= step.n, (r.id, step)
            if gentler.kind in ("secs", "secs_side"):
                assert gentler.n >= min(step.n, workouts.MIN_EASIER_SECONDS)


def test_a_knee_push_up_can_be_a_wall_push_up_and_a_lunge_a_squat():
    steps = workouts.play_steps(workouts.get("strength_30"))
    by_name = {s["name"]: s for s in steps}
    knee = by_name.get("Knee push-up")
    lunge = by_name.get("Reverse lunge")
    assert knee and lunge, "strength_30 has both moves"
    assert knee["easier"]["name"] == "Wall push-up" and knee["easier"]["reps"] == knee["reps"]
    assert lunge["easier"]["name"] == "Bodyweight squat" and lunge["easier"]["mode"] == "reps"
    assert lunge["easier"]["amount"] == f"{lunge['reps']} reps", "squats are not 'each side'"


def test_a_plank_gets_shorter_but_never_below_ten_seconds():
    assert workouts.easier_step(workouts.Step("plank", "secs", 30)) == workouts.Step("plank", "secs", 15)
    assert workouts.easier_step(workouts.Step("plank", "secs", 16)) == workouts.Step("plank", "secs", 10)
    assert workouts.easier_step(workouts.Step("plank", "secs", 8)) == workouts.Step("plank", "secs", 8)
    assert workouts.easier_step(workouts.Step("squat", "reps", 10)) is None


def test_every_player_entry_says_whether_it_has_an_easier_version():
    for r in workouts.ROUTINES:
        for s in workouts.play_steps(r):
            assert "easier" in s, r.id
            if s["mode"] == "rest":
                assert s["easier"] is None
            if s["easier"] is not None:
                e = s["easier"]
                assert e["mode"] in ("timed", "reps") and set(e) == {"name", "cue", "amount", "mode", "seconds", "reps"}
                assert (e["seconds"] or 0) > 0 if e["mode"] == "timed" else (e["reps"] or 0) > 0


def test_the_easier_version_is_in_the_persons_language_and_never_about_calories():
    for lang in SUPPORTED:
        for r in workouts.ROUTINES:
            for s in workouts.play_steps(r, lang):
                e = s["easier"]
                if e:
                    assert not re.search(r"kcal|calor|burn|earn", f"{e['name']} {e['cue']}", re.I)
    es = {s["name"]: s for s in workouts.play_steps(workouts.get("strength_30"), "es")}
    knee = es[workouts.t("es", "Knee push-up")]
    assert knee["easier"]["name"] == workouts.t("es", "Wall push-up") != "Wall push-up"
