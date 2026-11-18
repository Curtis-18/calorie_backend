from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, Numeric, SmallInteger, String, Text, BigInteger
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.sql import func

from app.core.database import Base


class Recipe(Base):
    """A person's own recipe ("house recipe"). Private to its owner for now.

    Nutrition per serving is computed from the ingredients on the server
    (see services/recipe_nutrition.py), never typed in for an ingredient-based
    recipe. Deleted softly so a later creator program can still count past logs.
    """

    __tablename__ = "recipes"

    id = Column(PGUUID(as_uuid=True), primary_key=True)  # chosen by the app, so a retry is safe
    owner_id = Column(PGUUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    servings = Column(Numeric(7, 2), nullable=False, default=1)
    visibility = Column(String, nullable=False, default="private")  # private | friends | public (only private is used so far)
    region = Column(String, nullable=True)
    tags = Column(JSONB, nullable=False, default=list)
    steps = Column(JSONB, nullable=False, default=list)
    calories_per_serving = Column(Integer, nullable=False)
    protein_g = Column(Float, nullable=False, default=0)
    carbs_g = Column(Float, nullable=False, default=0)
    fat_g = Column(Float, nullable=False, default=0)
    nutrients = Column(JSONB, nullable=True)  # known extras per serving; null = unknown
    basis = Column(String, nullable=False, default="ingredients")  # ingredients | manual | ai_estimate
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)


class RecipeIngredient(Base):
    __tablename__ = "recipe_ingredients"

    recipe_id = Column(PGUUID(as_uuid=True), ForeignKey("recipes.id", ondelete="CASCADE"), primary_key=True)
    position = Column(SmallInteger, primary_key=True)
    name = Column(String, nullable=False)
    grams = Column(Numeric(9, 2), nullable=False)
    fdc_id = Column(BigInteger, nullable=True)
    source = Column(String, nullable=False)  # usda | manual
    calories_per_100g = Column(Float, nullable=False)
    protein_g_per_100g = Column(Float, nullable=False, default=0)
    carbs_g_per_100g = Column(Float, nullable=False, default=0)
    fat_g_per_100g = Column(Float, nullable=False, default=0)
    nutrients_per_100g = Column(JSONB, nullable=True)
    is_baseline = Column(Boolean, nullable=False, default=False)  # the usual cooking oil, spice paste...


class RecipeEvent(Base):
    """Written quietly from the first day recipes exist, never shown to anyone.

    No view events on purpose: views are not part of any payout and are a
    privacy and gaming risk.
    """

    __tablename__ = "recipe_events"

    id = Column(PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    recipe_id = Column(PGUUID(as_uuid=True), ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False)
    actor_id = Column(PGUUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)
    kind = Column(String, nullable=False)  # save | log | share | cook
    log_entry_id = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
