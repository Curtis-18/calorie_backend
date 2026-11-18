import uuid

from sqlalchemy import Column, Date, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from app.core.database import Base


class AiUsage(Base):
    """How many times a person used one AI feature on one (device-local) day.

    The product meter, as opposed to rate_limit.py (the abuse guard). Only
    counted after a successful result, so a failed scan never uses up a free
    allowance. A table of its own, written in a savepoint, so deploying before
    the migration can't break scanning.
    """

    __tablename__ = "ai_usage"

    user_id = Column(PGUUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True)
    day = Column(Date, primary_key=True)
    feature = Column(String, primary_key=True)
    count = Column(Integer, nullable=False, default=0)
