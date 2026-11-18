from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.sql import func

from app.core.database import Base


class Message(Base):
    """A text message from one friend to another. The id comes from the app so
    a retry after a lost response can't send it twice."""

    __tablename__ = "messages"

    id = Column(PGUUID(as_uuid=True), primary_key=True)
    sender_id = Column(PGUUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)
    recipient_id = Column(PGUUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)
    body = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    read_at = Column(DateTime(timezone=True), nullable=True)


class MessageAttachment(Base):
    """Something attached to a message (a recipe card). Its own table, read in a
    savepoint, so a missing migration only means chat shows the plain text."""

    __tablename__ = "message_attachments"

    message_id = Column(PGUUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True)
    attachment = Column(JSONB, nullable=False)
