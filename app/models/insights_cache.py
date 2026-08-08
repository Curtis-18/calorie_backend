from sqlalchemy import Column, Date, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PGUUID, JSONB

from app.core.database import Base


class InsightsCache(Base):
    __tablename__ = "insights_cache"

    user_id = Column(PGUUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True)
    date = Column(Date, nullable=False)
    payload = Column(JSONB, nullable=False)
    generated_at = Column(DateTime, nullable=False)