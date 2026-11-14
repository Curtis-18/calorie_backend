import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.sql import func

from app.core.database import Base


class ProfileAvatar(Base):
    """A person's profile picture. Its own table (not a column on profiles) so
    a deploy that lands before the migration can't break anything that reads
    profiles."""

    __tablename__ = "profile_avatars"

    user_id = Column(PGUUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True)
    storage_path = Column(String, nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Story(Base):
    """A food photo every friend can see for 24 hours. The id comes from the
    app so a retry after a lost response can't post it twice."""

    __tablename__ = "stories"

    id = Column(PGUUID(as_uuid=True), primary_key=True)
    user_id = Column(PGUUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False, index=True)
    storage_path = Column(String, nullable=False)
    caption = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)


class StoryView(Base):
    __tablename__ = "story_views"

    story_id = Column(PGUUID(as_uuid=True), ForeignKey("stories.id", ondelete="CASCADE"), primary_key=True)
    viewer_id = Column(PGUUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True)
    viewed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    reaction = Column(String, nullable=True)
    reacted_at = Column(DateTime(timezone=True), nullable=True)


class ContentReport(Base):
    """A report of a story or a profile picture (App Store guideline 1.2).
    No foreign key to the content: the report must outlive it."""

    __tablename__ = "content_reports"

    id = Column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    reporter_id = Column(PGUUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False)
    reported_user_id = Column(PGUUID(as_uuid=True), nullable=False)
    kind = Column(String, nullable=False)  # 'story' | 'avatar' | 'message'
    subject_id = Column(PGUUID(as_uuid=True), nullable=True)
    reason = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
