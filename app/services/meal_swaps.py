"""Which of a person's own saved recipes fit what is left of today, and which
recipes a coach reply actually names (roadmap R8.4 step 4b).

Both are plain code, not the model: the ranking is arithmetic on the person's
own numbers, and a "Log this" button is only ever offered for a recipe whose
exact title appears in the reply, with the numbers read from the database. So
the model can phrase a suggestion but can never invent a recipe, a figure or a
button.

Nothing here rewards eating less: a recipe fits when it is no bigger than what
is left, and the better fits are the ones that use that room and cover the
protein still wanted.
"""

import re

MAX_FITS = 3
MAX_SUGGESTIONS = 3
# Below this there is no room for a meal today, so nothing is offered.
MIN_ROOM_KCAL = 100
MIN_TITLE_LENGTH = 3


def _score(recipe: dict, left_kcal: int, left_protein: int) -> float:
    protein_cover = 1.0 if left_protein <= 0 else min(recipe["protein_g"], left_protein) / left_protein
    room_used = max(0.0, 1 - abs(left_kcal - recipe["calories"]) / left_kcal)
    return 0.6 * protein_cover + 0.4 * room_used


def rank_fits(recipes: list[dict], left_kcal: int, left_protein: int, limit: int = MAX_FITS) -> list[dict]:
    """Up to [limit] recipes that fit in [left_kcal], best first (ties by title,
    so the answer never changes between two identical calls)."""
    if left_kcal < MIN_ROOM_KCAL:
        return []
    fitting = [r for r in recipes if 0 < r["calories"] <= left_kcal]
    fitting.sort(key=lambda r: (-_score(r, left_kcal, left_protein), r["title"].lower()))
    return fitting[:limit]


def named_in(reply: str, recipes: list[dict], limit: int = MAX_SUGGESTIONS) -> list[dict]:
    """The recipes whose whole title appears in [reply], in the order they are
    mentioned. A title must stand as its own words ("Rice" is not found in
    "Price"), and very short titles are ignored."""
    found: list[tuple[int, dict]] = []
    seen: set = set()
    for recipe in recipes:
        title = " ".join(recipe["title"].split())
        if len(title) < MIN_TITLE_LENGTH or recipe["id"] in seen:
            continue
        match = re.search(r"(?<!\w)" + re.escape(title) + r"(?!\w)", reply, re.IGNORECASE)
        if match:
            seen.add(recipe["id"])
            found.append((match.start(), recipe))
    found.sort(key=lambda pair: pair[0])
    return [recipe for _, recipe in found[:limit]]
