from pydantic import BaseModel


class FoodSearchResult(BaseModel):
    fdc_id: int
    description: str
    # USDA dataType ("Foundation", "SR Legacy", "Survey (FNDDS)", "Branded").
    # The client ranks generic foods above branded ones with it.
    data_type: str | None = None
    calories_per_100g: float | None = None
    protein_g_per_100g: float | None = None
    carbs_g_per_100g: float | None = None
    fat_g_per_100g: float | None = None
    # Extra nutrients per 100 g; None = USDA has no value for this food.
    fiber_g_per_100g: float | None = None
    sugar_g_per_100g: float | None = None
    sodium_mg_per_100g: float | None = None
    iron_mg_per_100g: float | None = None
    calcium_mg_per_100g: float | None = None


class FoodSearchResponse(BaseModel):
    query: str
    results: list[FoodSearchResult]
