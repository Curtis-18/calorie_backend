from pydantic import BaseModel

class FoodSearchResult(BaseModel):
    fdc_id:int
    description:str
    calories_per_100g:float | None
    protein_g_per_100g:float | None
    carbs_g_per_100g:float | None
    fat_g_per_100g:float | None


class FoodSearchResponse(BaseModel):
    query:str
    results:list[FoodSearchResult]