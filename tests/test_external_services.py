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
