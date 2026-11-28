"""Roadmap R8.1 step 1f: Open Food Facts as the barcode fallback after USDA."""

import httpx

from app.models.food import FoodSearchResult
from app.routers import foods as foods_router
from app.services import openfoodfacts_service as off

CODE = "3017620422003"


def _product(**over):
    nutriments = {
        "energy-kcal_100g": 539, "proteins_100g": 6.3, "carbohydrates_100g": 57.5, "fat_100g": 30.9,
        "fiber_100g": 0, "sugars_100g": 56.3, "sodium_100g": 0.0428, "iron_100g": 0.0021, "calcium_100g": 0.1,
    }
    nutriments.update(over.pop("nutriments", {}))
    return {"product_name": "Hazelnut spread", "brands": "Ferrero, Nutella", "nutriments": nutriments, **over}


def _use(monkeypatch, handler):
    real = httpx.AsyncClient

    def factory(*a, **k):
        k["transport"] = httpx.MockTransport(handler)
        return real(*a, **k)

    monkeypatch.setattr(off.httpx, "AsyncClient", factory)


def _ok(product):
    return lambda request: httpx.Response(200, json={"status": 1, "product": product})


# ---- the mapping --------------------------------------------------------------

def test_a_product_becomes_a_per_100g_result_with_minerals_in_milligrams():
    r = off._result_from_product(_product())
    assert r.fdc_id == 0 and r.data_type == "Open Food Facts"
    assert r.description == "Ferrero Hazelnut spread"
    assert r.calories_per_100g == 539 and r.protein_g_per_100g == 6.3
    assert r.sodium_mg_per_100g == 42.8 and r.iron_mg_per_100g == 2.1 and r.calcium_mg_per_100g == 100
    assert r.fiber_g_per_100g == 0 and r.sugar_g_per_100g == 56.3


def test_a_product_sold_by_volume_is_per_100_ml():
    """A 330 ml cola says "product_quantity_unit": "ml" and its _100g values are per 100 ml."""
    assert off._result_from_product(_product(product_quantity_unit="ml")).per_unit == "ml"
    assert off._result_from_product(_product(product_quantity_unit="g")).per_unit == "g"
    assert off._result_from_product(_product()).per_unit == "g", "no unit: grams, as before"


def test_the_volume_unit_is_asked_for():
    assert "product_quantity_unit" in off._FIELDS.split(",")


def test_a_missing_nutrient_is_unknown_not_zero():
    p = _product()
    del p["nutriments"]["sodium_100g"], p["nutriments"]["fiber_100g"]
    r = off._result_from_product(p)
    assert r.sodium_mg_per_100g is None and r.fiber_g_per_100g is None


def test_kilojoules_are_used_when_kcal_is_missing():
    p = _product()
    del p["nutriments"]["energy-kcal_100g"]
    p["nutriments"]["energy_100g"] = 2255
    assert round(off._result_from_product(p).calories_per_100g) == 539


def test_products_that_cannot_be_trusted_are_not_used():
    assert off._result_from_product(_product(product_name="  ")) is None
    p = _product()
    del p["nutriments"]["energy-kcal_100g"]
    assert off._result_from_product(p) is None
    # A typo: 5 kcal for a food whose macros add up to ~540.
    assert off._result_from_product(_product(nutriments={"energy-kcal_100g": 5})) is None
    assert off._result_from_product(_product(nutriments={"energy-kcal_100g": -3})) is None


def test_the_brand_is_not_repeated_when_the_name_already_has_it():
    assert off._result_from_product(_product(product_name="Ferrero Nutella", brands="Ferrero")).description == "Ferrero Nutella"


# ---- the lookup ---------------------------------------------------------------

async def test_lookup_sends_only_the_barcode_and_a_generic_user_agent(monkeypatch):
    seen = {}

    def handler(request):
        seen["url"], seen["ua"] = str(request.url), request.headers["user-agent"]
        return httpx.Response(200, json={"status": 1, "product": _product()})

    _use(monkeypatch, handler)
    assert (await off.lookup_barcode(CODE)).description.endswith("Hazelnut spread")
    assert f"/product/{CODE}.json" in seen["url"]
    assert seen["ua"] == "NuStreak-Backend/1.0" and "@" not in seen["ua"]


async def test_not_found_and_failures_are_just_none(monkeypatch):
    _use(monkeypatch, lambda r: httpx.Response(200, json={"status": 0, "status_verbose": "product not found"}))
    assert await off.lookup_barcode(CODE) is None
    _use(monkeypatch, lambda r: httpx.Response(404, json={}))
    assert await off.lookup_barcode(CODE) is None
    _use(monkeypatch, lambda r: httpx.Response(503, text="down"))
    assert await off.lookup_barcode(CODE) is None
    _use(monkeypatch, lambda r: httpx.Response(200, text="<html>not json</html>"))
    assert await off.lookup_barcode(CODE) is None

    def boom(request):
        raise httpx.ConnectTimeout("slow")

    _use(monkeypatch, boom)
    assert await off.lookup_barcode(CODE) is None


# ---- the route ----------------------------------------------------------------

def _found():
    return FoodSearchResult(fdc_id=0, description="Hazelnut spread", data_type="Open Food Facts", calories_per_100g=539)


def _usda_says(monkeypatch, result):
    async def fake(code):
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(foods_router, "lookup_barcode", fake)


def _off_says(monkeypatch, result):
    calls = []

    async def fake(code):
        calls.append(code)
        return result

    monkeypatch.setattr(foods_router, "lookup_off_barcode", fake)
    return calls


def test_open_food_facts_is_tried_after_usda_misses(client, monkeypatch):
    _usda_says(monkeypatch, None)
    calls = _off_says(monkeypatch, _found())
    r = client.get("/foods/barcode", params={"code": CODE})
    assert r.status_code == 200 and r.json()["data_type"] == "Open Food Facts" and calls == [CODE]


def test_usda_wins_and_open_food_facts_is_not_called(client, monkeypatch):
    _usda_says(monkeypatch, FoodSearchResult(fdc_id=1, description="OAT BAR", data_type="Branded", calories_per_100g=400))
    calls = _off_says(monkeypatch, _found())
    assert client.get("/foods/barcode", params={"code": CODE}).json()["description"] == "OAT BAR"
    assert calls == []


def test_a_product_only_open_food_facts_knows_still_works_when_usda_is_down(client, monkeypatch):
    _usda_says(monkeypatch, httpx.ConnectError("usda down"))
    _off_says(monkeypatch, _found())
    assert client.get("/foods/barcode", params={"code": CODE}).status_code == 200


def test_both_missing_is_404_and_usda_down_with_no_fallback_hit_is_502(client, monkeypatch):
    _usda_says(monkeypatch, None)
    _off_says(monkeypatch, None)
    assert client.get("/foods/barcode", params={"code": CODE}).status_code == 404
    _usda_says(monkeypatch, httpx.ConnectError("usda down"))
    assert client.get("/foods/barcode", params={"code": CODE}).status_code == 502
