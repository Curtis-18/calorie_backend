import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, SmallInteger, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.sql import func

from app.core.database import Base


class NotificationPrefs(Base):
    """A person's notification choices. No row means every default applies."""

    __tablename__ = "notification_prefs"

    user_id = Column(PGUUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True)
    friend_snaps = Column(Boolean, nullable=False, default=True)
    reactions = Column(Boolean, nullable=False, default=True)
    streak_reminders = Column(Boolean, nullable=False, default=True)
    milestones = Column(Boolean, nullable=False, default=True)
    meal_nudge_hour = Column(SmallInteger, nullable=True)
    quiet_start = Column(SmallInteger, nullable=False, default=22)
    quiet_end = Column(SmallInteger, nullable=False, default=8)
    utc_offset_minutes = Column(Integer, nullable=False, default=0)
    paused_until = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class DeviceToken(Base):
    __tablename__ = "device_tokens"

    token = Column(String, primary_key=True)
    user_id = Column(PGUUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, index=True)
    platform = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class NotificationLog(Base):
    __tablename__ = "notification_log"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(PGUUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String, nullable=False)
    title = Column(String, nullable=False)
    body = Column(String, nullable=False)
    status = Column(String, nullable=False)
    dedupe_key = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
