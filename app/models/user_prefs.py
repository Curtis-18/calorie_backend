from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.sql import func

from app.core.database import Base


class UserPrefs(Base):
    """Small per-person food preferences. No row = nothing chosen.

    Its own table, written in savepoints, so a deploy before the migration
    only means nobody has a region hint.
    """

    __tablename__ = "user_prefs"

    user_id = Column(PGUUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True)
    region = Column(String, nullable=True)  # a key from services/regions.py
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
