from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.sql import func

from app.core.database import Base


class CoachMessage(Base):
    """One turn of the chat with the AI coach. The coach is not a user, so this
    is not the friend `messages` table. A person's own turn has an id chosen by
    the app, so a retry after a lost response can't store it twice."""

    __tablename__ = "coach_messages"

    id = Column(PGUUID(as_uuid=True), primary_key=True)
    user_id = Column(PGUUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)
    role = Column(String, nullable=False)  # user | coach
    body = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    tokens_in = Column(Integer, nullable=True)
    tokens_out = Column(Integer, nullable=True)

    __table_args__ = (Index("coach_messages_user_created", "user_id", "created_at"),)
