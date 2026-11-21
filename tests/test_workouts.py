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

def test_there_are_routines_of_five_fifteen_and_thirty_minutes():
    assert {r.minutes for r in workouts.ROUTINES} == {5, 15, 30}
    assert len({r.id for r in workouts.ROUTINES}) == len(workouts.ROUTINES)
    assert {r.focus for r in workouts.ROUTINES} <= set(workouts.FOCUS_LABELS)


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
