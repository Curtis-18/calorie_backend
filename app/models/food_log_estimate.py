from sqlalchemy import Column, ForeignKey, String

from app.core.database import Base


class FoodLogEstimate(Base):
    """Marks a logged entry whose numbers are an estimate rather than a
    database match, with the one-line basis shown to the person ("typical
    jollof rice cooked with oil").

    A table of its own, like FoodLogNutrients: every read and write of a food
    log would name a new column, so deploying before the migration would break
    logging itself. No row = an ordinary entry.
    """

    __tablename__ = "food_log_estimates"

    log_id = Column(String, ForeignKey("food_logs.id", ondelete="CASCADE"), primary_key=True)
    basis = Column(String, nullable=False)
