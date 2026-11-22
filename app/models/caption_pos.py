from sqlalchemy import Column, Float, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from app.core.database import Base


class SnapCaptionPosition(Base):
    """Where the caption strip sits on a bite's photo (0 top .. 1 bottom). Its
    own table, so a deploy that lands before the migration changes nothing:
    every caption then sits at the default spot."""

    __tablename__ = "snap_caption_positions"

    snap_id = Column(PGUUID(as_uuid=True), ForeignKey("snaps.id", ondelete="CASCADE"), primary_key=True)
    y = Column(Float, nullable=False)


class StoryCaptionPosition(Base):
    __tablename__ = "story_caption_positions"

    story_id = Column(PGUUID(as_uuid=True), ForeignKey("stories.id", ondelete="CASCADE"), primary_key=True)
    y = Column(Float, nullable=False)
