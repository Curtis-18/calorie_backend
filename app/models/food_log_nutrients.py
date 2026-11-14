from sqlalchemy import Column, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB

from app.core.database import Base


class FoodLogNutrients(Base):
    """Fibre, sugar, sodium, iron and calcium for one logged entry, as eaten.

    A table of its own rather than a column on food_logs: every read and write
    of a food log would name a new column, so deploying before the migration
    was run would have broken logging itself. This way a missing table only
    means no nutrient data. No row = unknown (a manual entry, or an entry from
    before this existed); a key missing from `nutrients` = unknown for that
    one nutrient.
    """

    __tablename__ = "food_log_nutrients"

    log_id = Column(String, ForeignKey("food_logs.id", ondelete="CASCADE"), primary_key=True)
    nutrients = Column(JSONB, nullable=False)
