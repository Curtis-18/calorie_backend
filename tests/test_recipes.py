"""Roadmap P3.1/P3.3: house recipes, their computed nutrition, one-tap logging."""

import uuid
from datetime import date, datetime
from types import SimpleNamespace

import pytest

from app.models.food import FoodSearchResult
from app.models.food_log import FoodLog
from app.models.recipe import Recipe, RecipeEvent, RecipeIngredient
from app.services.recipe_nutrition import Ingredient, compute_per_serving, scale

ME = uuid.UUID("00000000-0000-0000-0000-000000000001")
OTHER = uuid.UUID("00000000-0000-0000-0000-000000000002")
RID = uuid.UUID("11111111-1111-1111-1111-111111111111")


def ing(grams, cal=100.0, p=10.0, c=5.0, f=2.0, source="usda", extras=None):
    return Ingredient("x", grams, source, 1 if source == "usda" else None, cal, p, c, f, extras or {})


# ---- the maths (pure) ---------------------------------------------------------

def test_per_serving_is_the_sum_divided_by_servings():
    ps = compute_per_serving([ing(200, cal=100), ing(100, cal=50)], servings=2)
    assert ps.calories == round((200 + 50) / 2)
    assert ps.protein_g == round((20 + 10) / 2, 1)
    assert ps.basis == "ingredients"


def test_a_typed_ingredient_makes_the_recipe_manual():
    assert compute_per_serving([ing(100), ing(10, source="manual")], 1).basis == "manual"


def test_an_extra_nutrient_is_only_reported_when_every_ingredient_has_it():
    both = compute_per_serving([ing(100, extras={"fiber_g": 2}), ing(100, extras={"fiber_g": 3})], 1)
    assert both.nutrients == {"fiber_g": 5.0}
    one_missing = compute_per_serving([ing(100, extras={"fiber_g": 2}), ing(100)], 1)
    assert "fiber_g" not in one_missing.nutrients  # unknown is not zero


def test_bad_inputs_are_refused():
    with pytest.raises(ValueError):
        compute_per_serving([], 1)
    with pytest.raises(ValueError):
        compute_per_serving([ing(100)], 0)


def test_scaling_to_what_was_eaten():
    s = scale({"calories": 400, "protein_g": 20.0, "carbs_g": 30.0, "fat_g": 10.0, "nutrients": {"fiber_g": 3.0}}, 1.5)
    assert s == {"calories": 600, "protein_g": 30.0, "carbs_g": 45.0, "fat_g": 15.0, "nutrients": {"fiber_g": 4.5}}


# ---- the routes, with an in-memory fake database ------------------------------

class _Nested:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _Scalars:
    def __init__(self, rows):
        self.rows = rows

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None

    def scalars(self):
        return self

    def all(self):
        return self.rows


class MemDb:
    """Just enough of AsyncSession for these routes."""

    def __init__(self):
        self.recipes: dict = {}
        self.ingredients: list = []
        self.logs: dict = {}
        self.events: list = []
        self.committed = 0
        self.fail_flush = False
        self._pending: list = []

    async def get(self, model, key):
        return {Recipe: self.recipes, FoodLog: self.logs}[model].get(key)

    def add(self, obj):
        self._pending.append(obj)

    def add_all(self, objs):
        self._pending.extend(objs)

    async def flush(self):
        if self.fail_flush:
            raise RuntimeError("no such table")
        await self._store()

    async def _store(self):
        for o in self._pending:
            if isinstance(o, Recipe):
                o.deleted_at = getattr(o, "deleted_at", None)
                self.recipes[o.id] = o
            elif isinstance(o, RecipeIngredient):
                self.ingredients.append(o)
            elif isinstance(o, FoodLog):
                self.logs[o.id] = o
            elif isinstance(o, RecipeEvent):
                o.id = o.id or uuid.uuid4()
                self.events.append(o)
        self._pending = []

    async def commit(self):
        await self._store()
        self.committed += 1

    async def rollback(self):
        self._pending = []

    def begin_nested(self):
        return _Nested()

    async def execute(self, stmt):
        text = str(stmt)
        if "recipe_events" in text:
            wanted = set(stmt.compile().params.values())
            return _Scalars([e.id for e in self.events if e.log_entry_id in wanted])
        if "recipe_ingredients" in text:
            return _Scalars(sorted(self.ingredients, key=lambda i: i.position))
        return _Scalars(sorted(self.recipes.values(), key=lambda r: r.created_at or 0))


@pytest.fixture
def db(monkeypatch):
    from app.core.database import get_db
    from app.main import app
    from app.routers import logs, recipes

    mem = MemDb()

    async def fake():
        yield mem

    app.dependency_overrides[get_db] = fake
    # Nutrient rows for a log are a separate table; here just record the call.
    mem.nutrient_writes = []

    async def write(db_, log_id, known):
        mem.nutrient_writes.append((log_id, known))

    monkeypatch.setattr(recipes, "_write_nutrients", write)
    return mem


def usda(monkeypatch, foods: dict[int, FoodSearchResult], best=None):
    from app.services import usda_service

    async def by_ids(ids):
        return {i: foods[i] for i in ids if i in foods}

    async def best_match(name):
        return best

    monkeypatch.setattr(usda_service, "get_foods_by_ids", by_ids)
    monkeypatch.setattr(usda_service, "get_best_match", best_match)


RICE = FoodSearchResult(fdc_id=1, description="Rice", calories_per_100g=130, protein_g_per_100g=2.7, carbs_g_per_100g=28, fat_g_per_100g=0.3, fiber_g_per_100g=0.4)
CHICKEN = FoodSearchResult(fdc_id=2, description="Chicken", calories_per_100g=165, protein_g_per_100g=31, carbs_g_per_100g=0, fat_g_per_100g=3.6, fiber_g_per_100g=0)


def body(**kw):
    base = {
        "id": str(RID), "title": "  Chicken rice  ", "servings": 2,
        "ingredients": [{"name": "rice", "grams": 300, "fdc_id": 1}, {"name": "chicken", "grams": 200, "fdc_id": 2}],
    }
    base.update(kw)
    return base


def test_a_recipe_is_priced_from_usda_not_from_the_client(client, db, monkeypatch):
    usda(monkeypatch, {1: RICE, 2: CHICKEN})
    r = client.post("/recipes", json=body())
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["title"] == "Chicken rice"
    # (300 g rice + 200 g chicken) / 2 servings
    assert out["calories_per_serving"] == round((130 * 3 + 165 * 2) / 2)
    assert out["basis"] == "ingredients" and out["estimated"] is False
    assert out["nutrients"] == {"fiber_g": round((0.4 * 3 + 0) / 2, 1)}
    assert [i["fdc_id"] for i in out["ingredients"]] == [1, 2]
    assert out["visibility"] == "private"


def test_the_numbers_cannot_be_typed_for_an_ingredient_recipe(client, db, monkeypatch):
    usda(monkeypatch, {1: RICE})
    r = client.post("/recipes", json=body(ingredients=[{"name": "rice", "grams": 100, "fdc_id": 1}], per_serving={"calories": 1}))
    assert r.status_code == 422


def test_a_recipe_needs_ingredients_or_its_own_numbers(client, db):
    assert client.post("/recipes", json=body(ingredients=[])).status_code == 422


def test_an_unknown_ingredient_is_refused_by_name(client, db, monkeypatch):
    usda(monkeypatch, {1: RICE})
    r = client.post("/recipes", json=body(ingredients=[{"name": "dragon fruit", "grams": 100, "fdc_id": 99}]))
    assert r.status_code == 422 and "dragon fruit" in r.json()["detail"]
    assert db.recipes == {}


def test_an_ingredient_with_no_id_is_matched_by_name(client, db, monkeypatch):
    usda(monkeypatch, {}, best=RICE)
    r = client.post("/recipes", json=body(ingredients=[{"name": "rice", "grams": 100}], servings=1))
    assert r.status_code == 201 and r.json()["ingredients"][0]["fdc_id"] == 1


def test_a_typed_ingredient_makes_it_estimated(client, db, monkeypatch):
    usda(monkeypatch, {1: RICE})
    r = client.post("/recipes", json=body(ingredients=[
        {"name": "rice", "grams": 100, "fdc_id": 1},
        {"name": "my spice paste", "grams": 20, "per_100g": {"calories": 200, "fat_g": 10}, "is_baseline": True},
    ], servings=1))
    out = r.json()
    assert out["basis"] == "manual" and out["estimated"] is True
    assert out["ingredients"][1]["is_baseline"] is True


def test_a_recipe_with_only_its_own_numbers(client, db):
    r = client.post("/recipes", json={"id": str(RID), "title": "Nan's stew", "servings": 4, "per_serving": {"calories": 450, "protein_g": 30}})
    assert r.status_code == 201 and r.json()["calories_per_serving"] == 450 and r.json()["estimated"] is True


def test_a_retry_returns_the_saved_recipe_not_a_copy(client, db, monkeypatch):
    usda(monkeypatch, {1: RICE, 2: CHICKEN})
    assert client.post("/recipes", json=body()).status_code == 201
    again = client.post("/recipes", json=body())
    assert again.status_code == 200 and len(db.recipes) == 1 and len(db.ingredients) == 2


def test_someone_elses_id_is_a_conflict(client, db, monkeypatch):
    usda(monkeypatch, {1: RICE, 2: CHICKEN})
    db.recipes[RID] = SimpleNamespace(id=RID, owner_id=OTHER, deleted_at=None)
    assert client.post("/recipes", json=body()).status_code == 409


def test_missing_tables_say_unavailable_and_nothing_else(client, db, monkeypatch):
    usda(monkeypatch, {1: RICE, 2: CHICKEN})
    db.fail_flush = True
    r = client.post("/recipes", json=body())
    assert r.status_code == 503 and "try again" in r.json()["detail"]


def test_limits(client, db):
    assert client.post("/recipes", json=body(servings=0)).status_code == 422
    assert client.post("/recipes", json=body(title="  ")).status_code == 422
    assert client.post("/recipes", json=body(tags=["x"] * 11)).status_code == 422
    big = [{"name": f"i{n}", "grams": 1, "per_100g": {"calories": 1}} for n in range(61)]
    assert client.post("/recipes", json=body(ingredients=big)).status_code == 422
    assert client.post("/recipes", json=body(ingredients=[{"name": "x", "grams": -5, "per_100g": {"calories": 1}}])).status_code == 422


def test_someone_elses_recipe_is_not_found(client, db):
    db.recipes[RID] = SimpleNamespace(id=RID, owner_id=OTHER, deleted_at=None)
    assert client.get(f"/recipes/{RID}").status_code == 404
    assert client.delete(f"/recipes/{RID}").status_code == 404
    assert client.patch(f"/recipes/{RID}", json={"title": "mine now"}).status_code == 404
    assert client.post(f"/recipes/{RID}/log", json={"id": "l1", "meal_type": "lunch", "log_date": "2026-11-18", "timestamp": "2026-11-18T12:00:00"}).status_code == 404


def test_delete_is_soft_and_hides_it(client, db, monkeypatch):
    usda(monkeypatch, {1: RICE, 2: CHICKEN})
    client.post("/recipes", json=body())
    assert client.delete(f"/recipes/{RID}").status_code == 204
    assert db.recipes[RID].deleted_at is not None
    assert client.get(f"/recipes/{RID}").status_code == 404


def test_changing_servings_redivides_the_same_ingredients(client, db, monkeypatch):
    usda(monkeypatch, {1: RICE, 2: CHICKEN})
    client.post("/recipes", json=body())
    r = client.patch(f"/recipes/{RID}", json={"servings": 4, "title": "Bigger pot"})
    assert r.status_code == 200
    assert r.json()["calories_per_serving"] == round((130 * 3 + 165 * 2) / 4)
    assert r.json()["title"] == "Bigger pot"


def test_logging_a_recipe_makes_one_entry_and_a_quiet_event(client, db, monkeypatch):
    usda(monkeypatch, {1: RICE, 2: CHICKEN})
    client.post("/recipes", json=body())
    per = db.recipes[RID].calories_per_serving
    payload = {"id": "entry-1", "servings": 1.5, "meal_type": "dinner", "log_date": "2026-11-18", "timestamp": "2026-11-18T19:00:00"}
    r = client.post(f"/recipes/{RID}/log", json=payload)
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["name"] == "Chicken rice" and out["calories"] == round(per * 1.5)
    assert out["source"] == "manual"  # the app only knows manual and photo
    assert [(e.kind, e.log_entry_id) for e in db.events] == [("log", "entry-1")]
    assert db.nutrient_writes and db.nutrient_writes[0][0] == "entry-1"


def test_logging_twice_with_the_same_id_is_one_entry(client, db, monkeypatch):
    usda(monkeypatch, {1: RICE, 2: CHICKEN})
    client.post("/recipes", json=body())
    payload = {"id": "entry-1", "meal_type": "lunch", "log_date": "2026-11-18", "timestamp": "2026-11-18T12:00:00"}
    assert client.post(f"/recipes/{RID}/log", json=payload).status_code == 201
    assert client.post(f"/recipes/{RID}/log", json=payload).status_code == 200
    assert len(db.logs) == 1 and len(db.events) == 1


def test_an_entry_the_app_saved_first_still_gets_its_event_once(client, db, monkeypatch):
    usda(monkeypatch, {1: RICE, 2: CHICKEN})
    client.post("/recipes", json=body())
    # The app's own save path created the entry before it reported the recipe.
    db.logs["entry-9"] = SimpleNamespace(
        id="entry-9", user_id=ME, name="Chicken rice", calories=400, protein_g=1.0, carbs_g=1.0, fat_g=1.0,
        meal_type="dinner", source="manual", timestamp=datetime(2026, 11, 18, 19), log_date=date(2026, 11, 18),
    )
    payload = {"id": "entry-9", "meal_type": "dinner", "log_date": "2026-11-18", "timestamp": "2026-11-18T19:00:00"}
    assert client.post(f"/recipes/{RID}/log", json=payload).status_code == 200
    assert client.post(f"/recipes/{RID}/log", json=payload).status_code == 200
    assert [(e.kind, e.log_entry_id) for e in db.events] == [("log", "entry-9")]


def test_another_persons_entry_id_is_a_conflict(client, db, monkeypatch):
    usda(monkeypatch, {1: RICE, 2: CHICKEN})
    client.post("/recipes", json=body())
    db.logs["entry-1"] = SimpleNamespace(id="entry-1", user_id=OTHER)
    payload = {"id": "entry-1", "meal_type": "lunch", "log_date": "2026-11-18", "timestamp": "2026-11-18T12:00:00"}
    assert client.post(f"/recipes/{RID}/log", json=payload).status_code == 409


def test_every_route_needs_a_login(anon_client):
    assert anon_client.get("/recipes").status_code == 401
    assert anon_client.post("/recipes", json={}).status_code == 401
    assert anon_client.post(f"/recipes/{RID}/log", json={}).status_code == 401
