from sqlalchemy import Boolean, Column, DateTime, ForeignKey, SmallInteger, String
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.sql import func

from app.core.database import Base


class BudgetPrefs(Base):
    """How a person wants their calories shown. No row = the plain daily target.

    Its own small table, written in savepoints, so a deploy before the
    migration only means everyone sees the daily target.
    """

    __tablename__ = "budget_prefs"

    user_id = Column(PGUUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True)
    mode = Column(String, nullable=False, default="daily")        # 'daily' | 'weekly'
    week_start_day = Column(SmallInteger, nullable=False, default=0)  # 0 = Monday
    weights = Column(JSONB, nullable=True)                         # seven numbers adding to 7, or null
    nudges = Column(Boolean, nullable=False, default=False)        # the gentle "spread it" card
    dismissed_weeks = Column(JSONB, nullable=False, default=list)  # week-start dates the card was declined for
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
