import uuid

from sqlalchemy import Column, Date, DateTime, Float, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.sql import func

from app.core.database import Base


class WeightLog(Base):
    """One weigh-in per user per (device-local) day; a second one that day
    replaces the first."""

    __tablename__ = "weight_logs"
    __table_args__ = (UniqueConstraint("user_id", "log_date", name="weight_logs_user_day"),)

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(PGUUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, index=True)
    log_date = Column(Date, nullable=False)
    weight_kg = Column(Float, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
