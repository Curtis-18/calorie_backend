from pydantic import BaseModel

class DetectedFoodItem(BaseModel):
    name:str
    estimated_grams:float
    calories_per_100g: float | None
    estimated_calories: float | None
    protein_g_per_100g: float | None
    estimated_protein_g: float | None
    carbs_g_per_100g: float | None
    estimated_carbs_g: float | None
    fat_g_per_100g: float | None
    estimated_fat_g: float | None

class PhotoAnalysisResponse(BaseModel):
    items: list[DetectedFoodItem]