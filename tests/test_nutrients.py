"""Fibre, sugar, sodium, iron and calcium: reading USDA, targets, storing per entry."""

import uuid
from datetime import date, datetime

import pytest

from app.services.nutrients import NUTRIENT_KEYS, nutrient_targets
from app.services.usda_service import _extract_extras

ME = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _food(*pairs):
    return {"foodNutrients": [{"nutrientName": n, "unitName": u, "value": v} for n, u, v in pairs]}


def test_reads_the_five_nutrients_from_a_usda_food():
    # Names and units as the live API returns them for "Spinach, raw" (SR Legacy).
    extras = _extract_extras(_food(
        ("Calcium, Ca", "MG", 99.0), ("Iron, Fe", "MG", 2.71), ("Sodium, Na", "MG", 79.0),
        ("Fiber, total dietary", "G", 2.2), ("Total Sugars", "G", 0.42), ("Energy", "KCAL", 23),
    ))
    assert extras == {
        "fiber_g_per_100g": 2.2, "sugar_g_per_100g": 0.42, "sodium_mg_per_100g": 79.0,
        "iron_mg_per_100g": 2.71, "calcium_mg_per_100g": 99.0,
    }


def test_a_missing_nutrient_is_unknown_not_zero():
    extras = _extract_extras(_food(("Iron, Fe", "MG", 1.5)))
    assert extras["iron_mg_per_100g"] == 1.5
    assert all(extras[f"{k}_per_100g"] is None for k in NUTRIENT_KEYS if k != "iron_mg")


def test_a_real_zero_is_kept():
    assert _extract_extras(_food(("Fiber, total dietary", "G", 0)))["fiber_g_per_100g"] == 0.0


@pytest.mark.parametrize("name", ["Total Sugars", "Sugars, Total", "Sugars, total including NLEA", "Sugars, Total NLEA"])
def test_every_usda_spelling_of_total_sugars_is_read(name):
    assert _extract_extras(_food((name, "G", 10.4)))["sugar_g_per_100g"] == 10.4


def test_a_value_in_an_unexpected_unit_is_left_unknown():
    """Sodium in grams read as milligrams would be 1000x too low."""
    assert _extract_extras(_food(("Sodium, Na", "G", 0.4)))["sodium_mg_per_100g"] is None


@pytest.mark.parametrize("sex, age, iron, calcium", [
    ("female", 18, 18, 1000), ("female", 50, 18, 1000), ("female", 51, 8, 1200), ("female", 80, 8, 1200),
    ("male", 18, 8, 1000), ("male", 51, 8, 1000), ("male", 70, 8, 1000), ("male", 71, 8, 1200),
])
def test_iron_and_calcium_follow_the_reference_intakes(sex, age, iron, calcium):
    t = nutrient_targets(sex, age, 2000)
    assert (t["iron_mg"], t["calcium_mg"]) == (iron, calcium)


def test_fibre_scales_with_calories_and_sodium_is_a_fixed_limit():
    assert nutrient_targets("male", 30, 2000)["fiber_g"] == 28
    assert nutrient_targets("male", 30, 2500)["fiber_g"] == 35
    assert nutrient_targets("female", 30, 1200)["sodium_limit_mg"] == 2300
    assert "sugar_g" not in nutrient_targets("male", 30, 2000)  # no target for total sugars


# --- storing them per entry --------------------------------------------------

class _Entry:
    def __init__(self, log_id="entry-1", owner=ME):
        self.id, self.user_id = log_id, owner
        self.name, self.calories = "Spinach", 23
        self.protein_g, self.carbs_g, self.fat_g = 2.9, 3.6, 0.4
        self.meal_type, self.source = "lunch", "manual"
        self.timestamp, self.log_date = datetime(2026, 11, 14, 12, 0), date(2026, 11, 14)


class _Result:
    def __init__(self, rows=(), scalars=()):
        self._rows, self._scalars = list(rows), list(scalars)

    def all(self):
        return self._rows or self._scalars

    def scalars(self):
        return self

    def scalar_one_or_none(self):
        return self._scalars[0] if self._scalars else None


class _Savepoint:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Db:
    """A food log store with a nutrients table that can be made to fail, as it
    does before the migration is run."""

    def __init__(self, entries=(), nutrients=None, table_missing=False):
        self.entries = {e.id: e for e in entries}
        self.nutrients = dict(nutrients or {})
        self.table_missing = table_missing
        self.commits = 0

    def begin_nested(self):
        return _Savepoint()

    def add(self, entry):
        self.entries[entry.id] = entry

    async def get(self, _model, pk):
        return self.entries.get(pk)

    async def refresh(self, _entry):
        pass

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        pass

    async def execute(self, stmt):
        sql = " ".join(str(stmt).split())
        params = stmt.compile().params
        if "food_log_nutrients" in sql:
            if self.table_missing:
                raise RuntimeError('relation "food_log_nutrients" does not exist')
            if sql.startswith("INSERT"):
                self.nutrients[params["log_id"]] = params["nutrients"]
            elif sql.startswith("DELETE"):
                self.nutrients.pop(params["log_id_1"], None)
            else:
                return _Result(rows=list(self.nutrients.items()))
            return _Result()
        return _Result(scalars=list(self.entries.values()))


def _with_db(db):
    from app.core.database import get_db
    from app.main import app

    async def fake_db():
        yield db

    app.dependency_overrides[get_db] = fake_db
    return db


def _payload(**extra):
    return {
        "id": "entry-1", "name": "Spinach", "calories": 23, "protein_g": 2.9, "carbs_g": 3.6, "fat_g": 0.4,
        "meal_type": "lunch", "source": "manual", "timestamp": "2026-11-14T12:00:00", "log_date": "2026-11-14",
        **extra,
    }


def test_a_log_keeps_only_the_nutrients_that_are_known(client):
    db = _with_db(_Db())
    r = client.post("/logs", json=_payload(nutrients={"iron_mg": 2.7, "fiber_g": 2.2, "sodium_mg": None}))
    assert r.status_code == 201
    assert r.json()["nutrients"] == {"iron_mg": 2.7, "fiber_g": 2.2}
    assert db.nutrients == {"entry-1": {"iron_mg": 2.7, "fiber_g": 2.2}}


def test_a_log_without_nutrients_stores_none_and_says_so(client):
    db = _with_db(_Db())
    for extra in ({}, {"nutrients": None}, {"nutrients": {}}):
        r = client.post("/logs", json=_payload(**extra))
        assert r.status_code == 201 and r.json()["nutrients"] is None
    assert db.nutrients == {}


def test_old_clients_and_bad_amounts(client):
    _with_db(_Db())
    assert client.post("/logs", json=_payload(nutrients={"iron_mg": -1})).status_code == 422
    # an unknown key from a newer app is ignored rather than refused
    r = client.post("/logs", json=_payload(nutrients={"zinc_mg": 3, "iron_mg": 1}))
    assert r.status_code == 201 and r.json()["nutrients"] == {"iron_mg": 1}


def test_logging_still_works_before_the_migration_is_run(client):
    db = _with_db(_Db(table_missing=True))
    r = client.post("/logs", json=_payload(nutrients={"iron_mg": 2.7}))
    assert r.status_code == 201 and "entry-1" in db.entries
    r = client.get("/logs/today", params={"date": "2026-11-14"})
    assert r.status_code == 200 and r.json()[0]["nutrients"] is None
    assert client.patch("/logs/entry-1", json={"calories": 46, "nutrients": {"iron_mg": 5.4}}).status_code == 200


def test_reading_a_day_attaches_each_entrys_nutrients(client):
    _with_db(_Db(entries=[_Entry("a"), _Entry("b")], nutrients={"a": {"calcium_mg": 99.0}}))
    by_id = {e["id"]: e["nutrients"] for e in client.get("/logs/today", params={"date": "2026-11-14"}).json()}
    assert by_id == {"a": {"calcium_mg": 99.0}, "b": None}


def test_editing_replaces_clears_or_keeps_nutrients(client):
    db = _with_db(_Db(entries=[_Entry()], nutrients={"entry-1": {"iron_mg": 2.7}}))
    # not mentioned: kept
    r = client.patch("/logs/entry-1", json={"calories": 46})
    assert r.json()["nutrients"] == {"iron_mg": 2.7}
    # a new portion or food: replaced
    r = client.patch("/logs/entry-1", json={"nutrients": {"iron_mg": 5.4, "fiber_g": 4.4}})
    assert r.json()["nutrients"] == {"iron_mg": 5.4, "fiber_g": 4.4}
    # swapped for a food with no data: cleared, so it reads as unknown
    r = client.patch("/logs/entry-1", json={"nutrients": None})
    assert r.json()["nutrients"] is None and db.nutrients == {}
