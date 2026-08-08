from sqlalchemy import Column, String, Integer, Float, Date, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from app.core.database import Base


class FoodLog(Base):
    __tablename__ = "food_logs"

    id = Column(String, primary_key=True)  # client-generated, stored as-is
    user_id = Column(PGUUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String, nullable=False)
    calories = Column(Integer, nullable=False)
    protein_g = Column(Float, nullable=False, default=0)
    carbs_g = Column(Float, nullable=False, default=0)
    fat_g = Column(Float, nullable=False, default=0)
    meal_type = Column(String, nullable=False)
    source = Column(String, nullable=False)
    log_date = Column(Date, nullable=False, index=True)  # device-local date, drives the /today query
    timestamp = Column(DateTime, nullable=False)  # actual moment logged, for ordering within a day