from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.sql import func

from app.core.database import Base


class UserLanguage(Base):
    """The language a person last used the app in, so a push notification (sent
    when they are not making a request) can be written in it.

    Its own table, read and written in savepoints, so a deploy before the
    migration only means notifications stay in English.
    """

    __tablename__ = "user_language"

    user_id = Column(PGUUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), primary_key=True)
    language = Column(String, nullable=False)  # one of app.i18n.SUPPORTED
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
