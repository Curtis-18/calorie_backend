from sqlalchemy import Column, Integer, Float, String, ForeignKey, DateTime, Date
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.sql import func
from app.core.database import Base

class Target(Base):
    __tablename__ = "targets" # FIXED: Use double underscores

    user_id = Column(PGUUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True)
    date_of_birth = Column(Date, nullable=False)
    sex = Column(String, nullable=False)
    height_cm = Column(Float, nullable=False)
    weight_kg = Column(Float, nullable=False)
    activity_level = Column(String, nullable=False)
    goal = Column(String, nullable=False)
    bmr = Column(Float, nullable=False)
    tdee = Column(Float, nullable=False)
    calorie_target = Column(Integer, nullable=False)
    protein_g = Column(Integer, nullable=False)
    fat_g = Column(Integer, nullable=False)
    carbs_g = Column(Integer, nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
