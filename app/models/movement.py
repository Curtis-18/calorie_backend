from sqlalchemy import Column, Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.sql import func

from app.core.database import Base


class MovementLog(Base):
    """One time someone moved: a guided session or something logged by hand.
    Private to the person (roadmap R9)."""

    __tablename__ = "movement_logs"

    id = Column(PGUUID(as_uuid=True), primary_key=True)
    user_id = Column(PGUUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, index=True)
    log_date = Column(Date, nullable=False)
    slice = Column(String, nullable=False)  # strength | cardio | mobility | fun
    activity = Column(String, nullable=False)
    minutes = Column(Integer, nullable=False)
    intensity = Column(String, nullable=False)  # easy | moderate | hard
    routine_id = Column(String, nullable=True)
    source = Column(String, nullable=False)  # session | manual
    est_kcal = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class MovementPrefs(Base):
    """How movement relates to the calorie plan. No row = off (nothing added)."""

    __tablename__ = "movement_prefs"

    user_id = Column(PGUUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True)
    eat_back_percent = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
