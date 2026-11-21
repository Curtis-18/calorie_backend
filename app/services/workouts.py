"""A small curated library of bodyweight routines the coach may offer
(roadmap R8.4 step 4c).

The coach never invents exercises. It is told the routine names; when its reply
names one, the server attaches the routine from this file, written in the
person's language. So the moves, the reps and the safety line are fixed text we
can read and test, not something a model made up on the day.

Rules (handover R2.3): a routine is movement for its own sake. Nothing here
mentions calories, burning, earning or making up for food, and a workout is
never sized to a meal. Every routine needs no equipment, starts with a warm-up,
ends with a cool-down and carries a "stop if anything hurts" line.
"""

from dataclasses import dataclass

from app.i18n import t

SAFETY = "Stop if anything hurts or you feel dizzy. If you have a health condition or you are unsure, check with a doctor first."

# How an amount is written. Keys are the kind used in the routines below.
AMOUNTS = {
    "reps": "{n} reps",
    "reps_side": "{n} reps each side",
    "secs": "{n} seconds",
    "secs_side": "{n} seconds each side",
    "mins": "{n} minutes",
}

SECTION_TITLES = {"warm": "Warm-up", "main": "Main moves", "cool": "Cool-down"}
REPEAT = "Repeat the main moves {n} times, resting a little between."

FOCUS_LABELS = {"strength": "Strength", "walk": "Walking", "core": "Core and balance", "mobility": "Gentle movement"}

# id: (name, how to do it). Plain, widely taught moves a beginner can do at home.
EXERCISES: dict[str, tuple[str, str]] = {
    "march": ("March in place", "Lift your knees comfortably and swing your arms."),
    "shoulder_rolls": ("Shoulder rolls", "Roll your shoulders slowly back, then forward."),
    "side_reach": ("Side reach", "Reach one arm overhead and lean gently to the side."),
    "hip_circles": ("Hip circles", "Hands on your hips, draw slow circles with your hips."),
    "squat": ("Bodyweight squat", "Sit your hips back as if onto a chair, keep your chest up, then stand."),
    "wall_pushup": ("Wall push-up", "Hands on a wall, bend your elbows to bring your chest toward it, then push back."),
    "knee_pushup": ("Knee push-up", "On hands and knees, lower your chest toward the floor and push back up."),
    "glute_bridge": ("Glute bridge", "Lie on your back with knees bent, lift your hips, pause, lower slowly."),
    "reverse_lunge": ("Reverse lunge", "Step one foot back, lower gently, then step forward. Switch legs."),
    "plank": ("Plank", "Rest on your forearms, keep a straight line from head to hips and breathe steadily. Knees down is fine."),
    "dead_bug": ("Dead bug", "Lie on your back, arms up and knees bent. Lower the opposite arm and leg slowly, then switch."),
    "calf_raise": ("Standing calf raise", "Rise onto your toes, pause, lower slowly. Hold a wall for balance."),
    "easy_walk": ("Easy walk", "Walk slowly and let your shoulders loosen."),
    "brisk_walk": ("Brisk walk", "Walk at a pace where you can still talk."),
    "hamstring": ("Hamstring stretch", "Heel forward, hinge at the hips with a straight back until you feel a gentle stretch."),
    "quad_stretch": ("Standing quad stretch", "Hold a wall, bring one heel toward your seat and keep your knees together."),
    "childs_pose": ("Child's pose", "Sit back on your heels with your arms stretched forward and rest."),
    "breathing": ("Slow breathing", "Breathe in for four counts and out for six."),
}


@dataclass(frozen=True)
class Step:
    exercise: str
    kind: str  # a key of AMOUNTS
    n: int


@dataclass(frozen=True)
class Routine:
    id: str
    name: str
    minutes: int
    focus: str  # a key of FOCUS_LABELS
    summary: str
    warm: tuple[Step, ...]
    main: tuple[Step, ...]
    cool: tuple[Step, ...]
    rounds: int = 1


ROUTINES: tuple[Routine, ...] = (
    Routine(
        "reset_5", "5-minute reset", 5, "mobility",
        "A gentle stretch-and-move break you can do anywhere.",
        warm=(Step("march", "secs", 60),),
        main=(
            Step("shoulder_rolls", "reps", 10), Step("side_reach", "reps_side", 6),
            Step("hip_circles", "reps_side", 6), Step("calf_raise", "reps", 10),
        ),
        cool=(Step("breathing", "secs", 60),),
    ),
    Routine(
        "legs_5", "5-minute leg wake-up", 5, "strength",
        "Three simple leg moves when you are short on time.",
        warm=(Step("march", "secs", 45),),
        main=(Step("squat", "reps", 8), Step("glute_bridge", "reps", 8), Step("calf_raise", "reps", 8)),
        cool=(Step("quad_stretch", "secs_side", 20),),
        rounds=2,
    ),
    Routine(
        "full_15", "15-minute full body", 15, "strength",
        "Simple moves for your whole body, no equipment.",
        warm=(Step("march", "secs", 120), Step("shoulder_rolls", "reps", 10), Step("hip_circles", "reps_side", 8)),
        main=(
            Step("squat", "reps", 10), Step("wall_pushup", "reps", 10),
            Step("glute_bridge", "reps", 12), Step("dead_bug", "reps_side", 6),
        ),
        cool=(Step("hamstring", "secs_side", 30), Step("childs_pose", "secs", 45), Step("breathing", "secs", 60)),
        rounds=3,
    ),
    Routine(
        "core_15", "15-minute core and balance", 15, "core",
        "Steady core work with a little balance.",
        warm=(Step("march", "secs", 120), Step("hip_circles", "reps_side", 8)),
        main=(
            Step("dead_bug", "reps_side", 8), Step("plank", "secs", 30),
            Step("glute_bridge", "reps", 12), Step("calf_raise", "reps", 12),
        ),
        cool=(Step("childs_pose", "secs", 45), Step("hamstring", "secs_side", 30), Step("breathing", "secs", 60)),
        rounds=3,
    ),
    Routine(
        "walk_15", "15-minute walk", 15, "walk",
        "A steady walk. Take a hill or stairs if you like.",
        warm=(Step("easy_walk", "mins", 3),),
        main=(Step("brisk_walk", "mins", 10),),
        cool=(Step("easy_walk", "mins", 2),),
    ),
    Routine(
        "strength_30", "30-minute strength", 30, "strength",
        "A full session of bodyweight strength with rests between rounds.",
        warm=(Step("march", "secs", 180), Step("shoulder_rolls", "reps", 10), Step("hip_circles", "reps_side", 8)),
        main=(
            Step("squat", "reps", 12), Step("reverse_lunge", "reps_side", 8), Step("knee_pushup", "reps", 8),
            Step("glute_bridge", "reps", 15), Step("dead_bug", "reps_side", 8), Step("plank", "secs", 30),
        ),
        cool=(
            Step("quad_stretch", "secs_side", 30), Step("hamstring", "secs_side", 30),
            Step("childs_pose", "secs", 45), Step("breathing", "secs", 60),
        ),
        rounds=4,
    ),
    Routine(
        "walk_30", "30-minute walk", 30, "walk",
        "A longer steady walk, easy at the start and the end.",
        warm=(Step("easy_walk", "mins", 5),),
        main=(Step("brisk_walk", "mins", 20),),
        cool=(Step("easy_walk", "mins", 5),),
    ),
)

_BY_ID = {r.id: r for r in ROUTINES}

# A rough guide used by the tests to keep each routine's stated minutes honest.
SECONDS_PER_REP = 4
REST_SECONDS_PER_ROUND = 20


def _seconds(step: Step) -> int:
    if step.kind == "mins":
        return step.n * 60
    if step.kind == "secs":
        return step.n
    if step.kind == "secs_side":
        return step.n * 2
    if step.kind == "reps_side":
        return step.n * 2 * SECONDS_PER_REP
    return step.n * SECONDS_PER_REP


def estimated_seconds(routine: Routine) -> int:
    main = sum(_seconds(s) for s in routine.main) + (REST_SECONDS_PER_ROUND if routine.rounds > 1 else 0)
    return sum(_seconds(s) for s in routine.warm) + main * routine.rounds + sum(_seconds(s) for s in routine.cool)


def get(routine_id: str) -> Routine | None:
    return _BY_ID.get(routine_id)


def minutes_label(lang: str, minutes: int) -> str:
    return t(lang, AMOUNTS["mins"], n=minutes)


def names(lang: str) -> list[dict]:
    """What the coach is told it may offer: id, the name in the person's
    language, minutes and focus."""
    return [
        {"id": r.id, "title": t(lang, r.name), "minutes": r.minutes, "focus": r.focus}
        for r in ROUTINES
    ]


def _step(lang: str, step: Step) -> dict:
    name, cue = EXERCISES[step.exercise]
    return {"name": t(lang, name), "cue": t(lang, cue), "amount": t(lang, AMOUNTS[step.kind], n=step.n)}


def render(routine: Routine, lang: str = "en") -> dict:
    """The whole routine in [lang], ready to show: sections of steps."""
    sections = [
        {"title": t(lang, SECTION_TITLES["warm"]), "repeat": None, "steps": [_step(lang, s) for s in routine.warm]},
        {
            "title": t(lang, SECTION_TITLES["main"]),
            "repeat": t(lang, REPEAT, n=routine.rounds) if routine.rounds > 1 else None,
            "steps": [_step(lang, s) for s in routine.main],
        },
        {"title": t(lang, SECTION_TITLES["cool"]), "repeat": None, "steps": [_step(lang, s) for s in routine.cool]},
    ]
    return {
        "id": routine.id,
        "name": t(lang, routine.name),
        "duration": minutes_label(lang, routine.minutes),
        "focus": t(lang, FOCUS_LABELS[routine.focus]),
        "summary": t(lang, routine.summary),
        "sections": sections,
        "safety": t(lang, SAFETY),
    }


def every_phrase() -> set[str]:
    """Every English phrase this file can send, so a test can insist each one
    has a translation (the phrases are passed to t() by variable, which the
    literal-scanning test cannot see)."""
    phrases = {SAFETY, REPEAT, *AMOUNTS.values(), *SECTION_TITLES.values(), *FOCUS_LABELS.values()}
    for name, cue in EXERCISES.values():
        phrases |= {name, cue}
    for r in ROUTINES:
        phrases |= {r.name, r.summary}
    return phrases
