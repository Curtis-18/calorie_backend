import uuid
from datetime import date, datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.food_log import MAX_CALORIES, MAX_MACRO_G, NutrientsIn
from app.services.recipe_nutrition import MAX_SERVINGS, MIN_SERVINGS

MAX_INGREDIENTS = 60
MAX_STEPS = 40


class Per100In(BaseModel):
    """Values the author typed for an ingredient USDA doesn't have."""

    calories: float = Field(ge=0, le=1000, allow_inf_nan=False)
    protein_g: float = Field(0, ge=0, le=100, allow_inf_nan=False)
    carbs_g: float = Field(0, ge=0, le=100, allow_inf_nan=False)
    fat_g: float = Field(0, ge=0, le=100, allow_inf_nan=False)


class IngredientIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    grams: float = Field(gt=0, le=20000, allow_inf_nan=False)
    fdc_id: int | None = Field(None, gt=0)
    per_100g: Per100In | None = None  # only used when there is no fdc_id
    is_baseline: bool = False         # the usual cooking oil, spice paste...


class PerServingIn(BaseModel):
    calories: int = Field(ge=0, le=MAX_CALORIES)
    protein_g: float = Field(0, ge=0, le=MAX_MACRO_G, allow_inf_nan=False)
    carbs_g: float = Field(0, ge=0, le=MAX_MACRO_G, allow_inf_nan=False)
    fat_g: float = Field(0, ge=0, le=MAX_MACRO_G, allow_inf_nan=False)


def _clean_list(values: list[str], limit: int, each: int) -> list[str]:
    out = [v.strip() for v in values if v and v.strip()]
    if len(out) > limit or any(len(v) > each for v in out):
        raise ValueError("too long")
    return out


class RecipeIn(BaseModel):
    id: uuid.UUID
    title: str = Field(min_length=1, max_length=120)
    description: str | None = Field(None, max_length=1000)
    servings: float = Field(1, ge=MIN_SERVINGS, le=MAX_SERVINGS, allow_inf_nan=False)
    region: str | None = Field(None, max_length=60)
    tags: list[str] = Field(default_factory=list, max_length=10)
    steps: list[str] = Field(default_factory=list, max_length=MAX_STEPS)
    ingredients: list[IngredientIn] = Field(default_factory=list, max_length=MAX_INGREDIENTS)
    # Only for a recipe with no ingredient list: the author's own estimate per serving.
    per_serving: PerServingIn | None = None
    nutrients: NutrientsIn | None = None

    @field_validator("title")
    @classmethod
    def _title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("The title can't be empty.")
        return v

    @field_validator("tags")
    @classmethod
    def _tags(cls, v: list[str]) -> list[str]:
        return _clean_list(v, 10, 30)

    @field_validator("steps")
    @classmethod
    def _steps(cls, v: list[str]) -> list[str]:
        return _clean_list(v, MAX_STEPS, 1000)

    @model_validator(mode="after")
    def _one_source_of_numbers(self):
        if not self.ingredients and self.per_serving is None:
            raise ValueError("Add the ingredients, or enter the calories for one serving.")
        if self.ingredients and self.per_serving is not None:
            raise ValueError("Send either the ingredients or the numbers for one serving, not both.")
        return self


class RecipeUpdate(BaseModel):
    """Details, who can open it, and (optionally) a whole new ingredient list,
    which is re-priced on the server."""

    title: str | None = Field(None, min_length=1, max_length=120)
    description: str | None = Field(None, max_length=1000)
    servings: float | None = Field(None, ge=MIN_SERVINGS, le=MAX_SERVINGS, allow_inf_nan=False)
    region: str | None = Field(None, max_length=60)
    tags: list[str] | None = Field(None, max_length=10)
    steps: list[str] | None = Field(None, max_length=MAX_STEPS)
    visibility: Literal["private", "friends"] | None = None
    ingredients: list[IngredientIn] | None = Field(None, min_length=1, max_length=MAX_INGREDIENTS)


class MediaIn(BaseModel):
    image: str = Field(min_length=1)  # base64
    caption: str | None = Field(None, max_length=120)

    @field_validator("caption")
    @classmethod
    def _caption(cls, v: str | None) -> str | None:
        return (v or "").strip() or None


class RecipeLogIn(BaseModel):
    id: str = Field(min_length=1, max_length=300)  # the new food-log entry's id (client-made)
    servings: float = Field(1, gt=0, le=50, allow_inf_nan=False)
    meal_type: Literal["breakfast", "lunch", "dinner", "snack"]
    log_date: date
    timestamp: datetime

    @field_validator("timestamp")
    @classmethod
    def _naive(cls, v: datetime) -> datetime:
        return v.astimezone(timezone.utc).replace(tzinfo=None) if v.tzinfo else v


class ShareIn(BaseModel):
    id: uuid.UUID  # the chat message's id, chosen by the app so a retry sends it once


class CollectionIn(BaseModel):
    id: uuid.UUID
    name: str = Field(min_length=1, max_length=40)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Give the collection a name.")
        return v


class CollectionItemIn(BaseModel):
    recipe_id: uuid.UUID


class HighlightsIn(BaseModel):
    recipe_ids: list[uuid.UUID] = Field(max_length=6)

    @field_validator("recipe_ids")
    @classmethod
    def _unique(cls, v: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(set(v)) != len(v):
            raise ValueError("A recipe can only be pinned once.")
        return v
