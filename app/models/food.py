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


class FoodSearchResponse(BaseModel):
    query: str
    results: list[FoodSearchResult]
