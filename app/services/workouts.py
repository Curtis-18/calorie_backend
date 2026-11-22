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

FOCUS_LABELS = {
    "strength": "Strength", "walk": "Walking", "core": "Core and balance", "mobility": "Gentle movement",
    "cardio": "Cardio", "fun": "Dance and play",
}

# The four slices of the weekly "Move plate" in the app. Every focus belongs to one.
SLICES = ("strength", "cardio", "mobility", "fun")
FOCUS_SLICE = {"strength": "strength", "core": "strength", "walk": "cardio", "cardio": "cardio", "mobility": "mobility", "fun": "fun"}

LEVEL_LABELS = {"easy": "Easy", "steady": "Steady", "strong": "Strong"}
REST_LABEL = "Rest"

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
    "step_touch": ("Step touch", "Step to the side, bring your feet together and swing your arms. Switch sides."),
    "knee_lift": ("Gentle high knees", "Lift each knee toward your waist at a pace you can keep up."),
    "shadow_box": ("Shadow boxing", "Stand tall and punch forward in a steady rhythm, one arm at a time."),
    "step_jack": ("Step jacks", "Step one foot out and reach both arms up, then step back. Switch sides."),
    "free_dance": ("Free dance", "Put on a song you love and move however feels good."),
    "shake_out": ("Shake it out", "Shake your arms, then your legs, then everything."),
    "cat_cow": ("Cat-cow", "On hands and knees, round your back, then lift your chest and look forward. Move with your breath."),
    "spinal_twist": ("Gentle spinal twist", "Lie on your back, drop both knees to one side and rest. Switch sides."),
    "neck_tilts": ("Neck tilts", "Tilt one ear toward your shoulder and hold gently. Switch sides."),
    "bird_dog": ("Bird dog", "On hands and knees, reach one arm forward and the opposite leg back, hold, then switch."),
    "wall_sit": ("Wall sit", "Lean your back on a wall, slide down to a comfortable squat and hold."),
    "balance": ("Single-leg balance", "Stand on one foot next to a wall for support, hold, then switch."),
    "hip_flexor": ("Hip stretch", "Kneel on one knee, tuck your hips under and lean forward gently."),
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
    level: str = "easy"  # a key of LEVEL_LABELS


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
        rounds=3, level="steady",
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
        rounds=3, level="steady",
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
        rounds=4, level="strong",
    ),
    Routine(
        "walk_30", "30-minute walk", 30, "walk",
        "A longer steady walk, easy at the start and the end.",
        warm=(Step("easy_walk", "mins", 5),),
        main=(Step("brisk_walk", "mins", 20),),
        cool=(Step("easy_walk", "mins", 5),),
    ),
    Routine(
        "desk_2", "2-minute desk break", 2, "mobility",
        "Loosen your neck and shoulders, even from a chair.",
        warm=(Step("shoulder_rolls", "reps", 8),),
        main=(Step("neck_tilts", "secs_side", 15), Step("side_reach", "reps_side", 4)),
        cool=(Step("breathing", "secs", 30),),
    ),
    Routine(
        "dance_3", "3-minute dance break", 3, "fun",
        "One song, any moves you like.",
        warm=(Step("shake_out", "secs", 30),),
        main=(Step("free_dance", "secs", 120),),
        cool=(Step("breathing", "secs", 30),),
    ),
    Routine(
        "squat_3", "3-minute squat bite", 3, "strength",
        "A few squats and a wall sit to wake your legs.",
        warm=(Step("march", "secs", 30),),
        main=(Step("squat", "reps", 8), Step("wall_sit", "secs", 20)),
        cool=(Step("quad_stretch", "secs_side", 15),),
        rounds=2,
    ),
    Routine(
        "wake_3", "3-minute wake-up", 3, "cardio",
        "Gentle steps and knee lifts to get you moving.",
        warm=(Step("march", "secs", 30),),
        main=(Step("step_touch", "secs", 30), Step("knee_lift", "secs", 20)),
        cool=(Step("side_reach", "reps_side", 4),),
        rounds=2,
    ),
    Routine(
        "walk_10", "10-minute walk", 10, "walk",
        "A short, steady walk.",
        warm=(Step("easy_walk", "mins", 2),),
        main=(Step("brisk_walk", "mins", 6),),
        cool=(Step("easy_walk", "mins", 2),),
    ),
    Routine(
        "cardio_10", "10-minute gentle cardio", 10, "cardio",
        "Low-impact moves with no jumping, at a pace you can chat to.",
        warm=(Step("march", "secs", 90),),
        main=(
            Step("step_touch", "secs", 40), Step("knee_lift", "secs", 30),
            Step("shadow_box", "secs", 40), Step("step_jack", "secs", 30),
        ),
        cool=(Step("hamstring", "secs_side", 20), Step("breathing", "secs", 60)),
        rounds=3,
    ),
    Routine(
        "stretch_10", "10-minute full-body stretch", 10, "mobility",
        "Slow stretches from your neck to your calves.",
        warm=(Step("march", "secs", 60), Step("shoulder_rolls", "reps", 10)),
        main=(
            Step("neck_tilts", "secs_side", 20), Step("side_reach", "reps_side", 6),
            Step("hamstring", "secs_side", 30), Step("quad_stretch", "secs_side", 30),
            Step("hip_flexor", "secs_side", 30), Step("spinal_twist", "secs_side", 30),
        ),
        cool=(Step("childs_pose", "secs", 60), Step("breathing", "secs", 60)),
    ),
    Routine(
        "flow_10", "10-minute slow flow", 10, "mobility",
        "Unhurried moves linked with your breathing.",
        warm=(Step("breathing", "secs", 60), Step("shoulder_rolls", "reps", 10)),
        main=(
            Step("cat_cow", "reps", 8), Step("bird_dog", "reps_side", 6),
            Step("spinal_twist", "secs_side", 30), Step("childs_pose", "secs", 30),
        ),
        cool=(Step("hamstring", "secs_side", 30), Step("breathing", "secs", 60)),
        rounds=2,
    ),
    Routine(
        "balance_10", "10-minute balance and core", 10, "core",
        "Steady balance and core work, one thing at a time.",
        warm=(Step("march", "secs", 60), Step("hip_circles", "reps_side", 6)),
        main=(
            Step("balance", "secs_side", 30), Step("dead_bug", "reps_side", 6),
            Step("bird_dog", "reps_side", 6), Step("plank", "secs", 25),
        ),
        cool=(Step("childs_pose", "secs", 45), Step("breathing", "secs", 45)),
        rounds=2, level="steady",
    ),
    Routine(
        "play_5", "5-minute play break", 5, "fun",
        "Shake, step and dance a little, just for fun.",
        warm=(Step("shake_out", "secs", 30),),
        main=(Step("free_dance", "secs", 60), Step("step_jack", "secs", 20), Step("shadow_box", "secs", 20)),
        cool=(Step("breathing", "secs", 30),),
        rounds=2,
    ),
    Routine(
        "dance_15", "15-minute dance party", 15, "fun",
        "Dance, shadow box and step along to a song or two.",
        warm=(Step("shake_out", "secs", 60), Step("step_touch", "secs", 60)),
        main=(Step("free_dance", "secs", 120), Step("step_jack", "secs", 30), Step("shadow_box", "secs", 30)),
        cool=(Step("hamstring", "secs_side", 20), Step("breathing", "secs", 60)),
        rounds=4, level="steady",
    ),
    Routine(
        "cardio_20", "20-minute steady cardio", 20, "cardio",
        "Four rounds of low-impact cardio.",
        warm=(Step("march", "secs", 120),),
        main=(
            Step("step_touch", "secs", 60), Step("knee_lift", "secs", 45),
            Step("shadow_box", "secs", 60), Step("step_jack", "secs", 45),
        ),
        cool=(Step("hamstring", "secs_side", 30), Step("breathing", "secs", 60)),
        rounds=4, level="steady",
    ),
    Routine(
        "strength_20", "20-minute strength", 20, "strength",
        "Bodyweight strength with rests between rounds.",
        warm=(Step("march", "secs", 120), Step("shoulder_rolls", "reps", 10), Step("hip_circles", "reps_side", 8)),
        main=(
            Step("squat", "reps", 10), Step("wall_pushup", "reps", 10), Step("glute_bridge", "reps", 12),
            Step("reverse_lunge", "reps_side", 6), Step("dead_bug", "reps_side", 6),
        ),
        cool=(Step("quad_stretch", "secs_side", 30), Step("childs_pose", "secs", 45), Step("breathing", "secs", 45)),
        rounds=4, level="steady",
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
        # For the Workouts tab (the coach card ignores these).
        "minutes": routine.minutes,
        "slice": slice_of(routine),
        "level": routine.level,
        "level_label": t(lang, LEVEL_LABELS[routine.level]),
        "rounds": routine.rounds,
        "play": play_steps(routine, lang),
    }


def slice_of(routine: Routine) -> str:
    """Which slice of the weekly Move plate this routine fills."""
    return FOCUS_SLICE[routine.focus]


def card(routine: Routine, lang: str = "en") -> dict:
    """One routine as a card in the library (no steps)."""
    return {
        "id": routine.id,
        "name": t(lang, routine.name),
        "minutes": routine.minutes,
        "focus": t(lang, FOCUS_LABELS[routine.focus]),
        "slice": slice_of(routine),
        "level": routine.level,
        "level_label": t(lang, LEVEL_LABELS[routine.level]),
        "summary": t(lang, routine.summary),
    }


def library(lang: str = "en") -> dict:
    """Everything the Workouts tab lists, shortest first."""
    ordered = sorted(ROUTINES, key=lambda r: (r.minutes, r.id))
    return {"routines": [card(r, lang) for r in ordered], "slices": list(SLICES)}


def _play_entries(lang: str, section: str, step: Step, round_no: int | None) -> list[dict]:
    """One step as what the player shows. A step done on each side becomes two
    timed steps; a rep step stays one (the amount already says "each side")."""
    name, cue = EXERCISES[step.exercise]
    base = {
        "section": section, "round": round_no, "name": t(lang, name), "cue": t(lang, cue),
        "amount": t(lang, AMOUNTS[step.kind], n=step.n),
    }
    if step.kind == "secs":
        return [{**base, "mode": "timed", "seconds": step.n, "reps": None, "side": None}]
    if step.kind == "secs_side":
        return [{**base, "mode": "timed", "seconds": step.n, "reps": None, "side": side} for side in (1, 2)]
    if step.kind == "mins":
        return [{**base, "mode": "timed", "seconds": step.n * 60, "reps": None, "side": None}]
    return [{**base, "mode": "reps", "seconds": None, "reps": step.n, "side": None}]


def play_steps(routine: Routine, lang: str = "en") -> list[dict]:
    """The routine as one flat list for the player: warm-up, the main moves
    round after round with a short rest between rounds, then the cool-down."""
    out: list[dict] = []
    for step in routine.warm:
        out += _play_entries(lang, "warm", step, None)
    for round_no in range(1, routine.rounds + 1):
        for step in routine.main:
            out += _play_entries(lang, "main", step, round_no)
        if routine.rounds > 1:
            out.append({
                "section": "main", "round": round_no, "mode": "rest", "name": t(lang, REST_LABEL), "cue": "",
                "amount": t(lang, AMOUNTS["secs"], n=REST_SECONDS_PER_ROUND),
                "seconds": REST_SECONDS_PER_ROUND, "reps": None, "side": None,
            })
    for step in routine.cool:
        out += _play_entries(lang, "cool", step, None)
    return out


def every_phrase() -> set[str]:
    """Every English phrase this file can send, so a test can insist each one
    has a translation (the phrases are passed to t() by variable, which the
    literal-scanning test cannot see)."""
    phrases = {SAFETY, REPEAT, REST_LABEL, *AMOUNTS.values(), *SECTION_TITLES.values(), *FOCUS_LABELS.values(), *LEVEL_LABELS.values()}
    for name, cue in EXERCISES.values():
        phrases |= {name, cue}
    for r in ROUTINES:
        phrases |= {r.name, r.summary}
    return phrases
