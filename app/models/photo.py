from pydantic import BaseModel


class EstimatedFood(BaseModel):
    """One food Gemini spotted in a photo, with USDA macros when matched.

    `name` and `estimated_grams` are what older clients read; the rest lets
    the client skip one USDA lookup per food.
    """

    name: str
    estimated_grams: float
    matched: bool = False
    # What the name was matched to, so the app can show it and let the user
    # correct a wrong match. Both None when unmatched.
    matched_description: str | None = None
    matched_fdc_id: int | None = None
    calories_per_100g: float | None = None
    protein_g_per_100g: float | None = None
    carbs_g_per_100g: float | None = None
    fat_g_per_100g: float | None = None
