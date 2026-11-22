import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.sql import func

from app.core.database import Base


class Activity(Base):
    """One line of the in-app Notifications list: a friend sent a bite, or
    reacted to one. Messages and friend requests are deliberately not here."""

    __tablename__ = "activity"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(PGUUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_id = Column(PGUUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)
    kind = Column(String, nullable=False)  # "bite" | "reaction"
    emoji = Column(String, nullable=True)
    dedupe_key = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    seen_at = Column(DateTime(timezone=True), nullable=True)
