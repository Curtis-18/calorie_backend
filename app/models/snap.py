import uuid

from sqlalchemy import Column, Date, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.sql import func

from app.core.database import Base


class Snap(Base):
    """A food photo sent to friends. The id comes from the app so a retry
    after a lost response can't send it twice."""

    __tablename__ = "snaps"

    id = Column(PGUUID(as_uuid=True), primary_key=True)
    sender_id = Column(PGUUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, index=True)
    storage_path = Column(String, nullable=False)
    caption = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)


class SnapRecipient(Base):
    __tablename__ = "snap_recipients"

    snap_id = Column(PGUUID(as_uuid=True), ForeignKey("snaps.id", ondelete="CASCADE"), primary_key=True)
    recipient_id = Column(PGUUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True)
    viewed_at = Column(DateTime(timezone=True), nullable=True)
    reaction = Column(String, nullable=True)
    reacted_at = Column(DateTime(timezone=True), nullable=True)


class SnapDay(Base):
    """One row per sender, recipient and day: the raw material of a pair streak."""

    __tablename__ = "snap_days"

    sender_id = Column(PGUUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True)
    recipient_id = Column(PGUUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True)
    day = Column(Date, primary_key=True)


class SnapReport(Base):
    __tablename__ = "snap_reports"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    reporter_id = Column(PGUUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)
    reported_user_id = Column(PGUUID(as_uuid=True), nullable=False)
    snap_id = Column(PGUUID(as_uuid=True), nullable=True)
    reason = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
