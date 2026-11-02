import pytest

from app.services.gemini_service import _extract_items
from app.services.usda_service import _extract_nutrients


def _nutrients(*pairs):
    return [{"nutrientName": n, "unitName": u, "value": v} for n, u, v in pairs]


def test_usda_nutrients_normal():
    out = _extract_nutrients(
        {
            "foodNutrients": _nutrients(
                ("Energy", "KCAL", 52.0),
                ("Protein", "G", 0.3),
                ("Total lipid (fat)", "G", 0.2),
                ("Carbohydrate, by difference", "G", 13.8),
            )
        }
    )
    assert out == {
        "calories": 52.0,
        "protein_g": 0.3,
        "fat_g": 0.2,
        "carbs_g": 13.8,
    }


def test_usda_accepts_nlea_aliases():
    out = _extract_nutrients(
        {
            "foodNutrients": _nutrients(
                ("Energy", "KCAL", 100.0),
                ("Carbohydrate, by difference (NLEA)", "G", 12.0),
                ("Total lipid (fat) (NLEA)", "G", 3.0),
            )
        }
    )
    assert out["carbs_g"] == 12.0
    assert out["fat_g"] == 3.0


def test_usda_ignores_kilojoules():
    """'Energy' in kJ must not be reported as calories."""
    out = _extract_nutrients({"foodNutrients": _nutrients(("Energy", "kJ", 900.0))})
    assert out["calories"] is None


def test_usda_survives_missing_nutrients():
    assert _extract_nutrients({}) == {
        "calories": None,
        "protein_g": None,
        "fat_g": None,
        "carbs_g": None,
    }


def test_gemini_parses_items():
    data = {"candidates": [{"content": {"parts": [{"text": '[{"name": "Eggs", "estimated_grams": 100}]'}]}}]}
    assert _extract_items(data) == [{"name": "Eggs", "estimated_grams": 100.0}]


def test_gemini_drops_unusable_rows():
    raw = '[{"name":"Eggs","estimated_grams":100},{"name":"","estimated_grams":5},{"estimated_grams":5},{"name":"Mystery","estimated_grams":0},{"name":"Toast","estimated_grams":"80"}]'
    data = {"candidates": [{"content": {"parts": [{"text": raw}]}}]}
    assert _extract_items(data) == [
        {"name": "Eggs", "estimated_grams": 100.0},
        {"name": "Toast", "estimated_grams": 80.0},
    ]


def test_gemini_empty_array_is_valid():
    data = {"candidates": [{"content": {"parts": [{"text": "[]"}]}}]}
    assert _extract_items(data) == []


def test_gemini_blocked_response_raises_cleanly():
    """Previously this was an IndexError surfacing as an opaque 500."""
    with pytest.raises(RuntimeError, match="nothing"):
        _extract_items({"promptFeedback": {"blockReason": "SAFETY"}})


def test_gemini_no_candidates_raises_cleanly():
    with pytest.raises(RuntimeError, match="no candidates"):
        _extract_items({})


def test_gemini_empty_text_raises_cleanly():
    with pytest.raises(RuntimeError, match="empty"):
        _extract_items({"candidates": [{"content": {"parts": []}}]})


def test_gemini_non_array_raises_cleanly():
    data = {"candidates": [{"content": {"parts": [{"text": '{"narrative": "hi"}'}]}}]}
    with pytest.raises(RuntimeError, match="non-array"):
        _extract_items(data)


# --- shapes captured from live FoodData Central responses (Nov 2026) --------

def _n(name, unit, value):
    return {"nutrientName": name, "unitName": unit, "value": value}


def test_foundation_food_with_only_atwater_energy_gets_calories():
    """Regression: "Apples, gala, with skin, raw" (Foundation) has no plain
    "Energy" nutrient, so it came back with calories=None and was dropped."""
    out = _extract_nutrients({"foodNutrients": [
        _n("Total lipid (fat)", "G", 0.15),
        _n("Protein", "G", 0.133),
        _n("Carbohydrate, by difference", "G", 14.8),
        _n("Energy (Atwater General Factors)", "KCAL", 61.0),
        _n("Energy (Atwater Specific Factors)", "KCAL", 54.9),
    ]})
    assert out["calories"] == 54.9  # specific factors, consistent with SR Legacy
    assert out["carbs_g"] == 14.8


def test_plain_energy_wins_over_atwater_and_kj_is_ignored():
    out = _extract_nutrients({"foodNutrients": [
        _n("Energy", "kJ", 357),
        _n("Energy (Atwater General Factors)", "KCAL", 90.0),
        _n("Energy", "KCAL", 85.0),
    ]})
    assert out["calories"] == 85.0


def test_carbohydrate_by_summation_is_a_fallback():
    out = _extract_nutrients({"foodNutrients": [_n("Carbohydrate, by summation", "G", 18.0)]})
    assert out["carbs_g"] == 18.0


def test_plausibility_check():
    from app.services.usda_service import is_plausible

    # Branded "OLIVE OIL" at 0 kcal per 100 g but 93 g fat: broken.
    assert not is_plausible({"calories": 0.0, "protein_g": 0, "carbs_g": 0, "fat_g": 93.3})
    # Real olive oil, a label rounding its way to 800-900: fine.
    assert is_plausible({"calories": 800.0, "protein_g": 0, "carbs_g": 0, "fat_g": 93.3})
    # Diet soda and water: 0 kcal, no macros: fine.
    assert is_plausible({"calories": 0.0, "protein_g": 0, "carbs_g": 0, "fat_g": 0})
    # Whiskey: calories come from alcohol.
    assert is_plausible({"calories": 250.0, "protein_g": 0, "carbs_g": 0, "fat_g": 0}, alcohol_g=36)
    # Sugar-free sweets: sugar alcohols count as carbs but carry fewer kcal.
    assert is_plausible({"calories": 150.0, "protein_g": 0, "carbs_g": 70, "fat_g": 0})
    # Stated calories wildly above what the macros allow: broken.
    assert not is_plausible({"calories": 900.0, "protein_g": 5, "carbs_g": 20, "fat_g": 1})


async def test_search_skips_broken_branded_rows_but_keeps_lab_data(monkeypatch):
    import httpx

    from app.services import usda_service

    payload = {"foods": [
        {"fdcId": 1, "description": "OLIVE OIL", "dataType": "Branded",
         "foodNutrients": [_n("Energy", "KCAL", 0.0), _n("Total lipid (fat)", "G", 93.3)]},
        {"fdcId": 2, "description": "Olive oil", "dataType": "Survey (FNDDS)",
         "foodNutrients": [_n("Energy", "KCAL", 900), _n("Total lipid (fat)", "G", 100)]},
        {"fdcId": 3, "description": "Apples, gala, with skin, raw", "dataType": "Foundation",
         "foodNutrients": [_n("Energy (Atwater Specific Factors)", "KCAL", 54.9)]},
    ]}
    real = httpx.AsyncClient

    def fake_client(*a, **kw):
        kw["transport"] = httpx.MockTransport(lambda r: httpx.Response(200, json=payload))
        return real(*a, **kw)

    monkeypatch.setattr(usda_service.httpx, "AsyncClient", fake_client)
    results = await usda_service.search_foods("olive oil")
    assert [r.fdc_id for r in results] == [2, 3]
    assert results[1].calories_per_100g == 54.9
