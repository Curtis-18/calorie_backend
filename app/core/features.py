"""Which AI features exist, who may use them, and how often they are used.

Every AI route calls `require_feature` before doing work and `record_usage`
after a successful result. Today `require_feature` always allows: the point is
that the paywall (handover: PRODUCT ROADMAP P6) later only has to change what
this answers, not touch every route. `record_usage` already counts, so the
free limit can be chosen from real numbers instead of a guess.
"""

import enum
import logging
import uuid
from datetime import date as date_type

from sqlalchemy.dialects.postgresql import insert

from app.core import database
from app.models.ai_usage import AiUsage

log = logging.getLogger("calorie_backend")


class Feature(str, enum.Enum):
    PHOTO_SCAN = "photo_scan"
    BARCODE_LOOKUP = "barcode_lookup"  # unlimited for everyone, listed so the rule is visible
    VOICE_NOTE = "voice_note"
    COACH_CHAT = "coach_chat"
    WEEKLY_REPORT = "weekly_report"
    INSIGHTS = "insights"  # the AI narrative on Insights; counted per real generation, not per cache hit
    MENU_SCAN = "menu_scan"
    FRIDGE_SCAN = "fridge_scan"
    RECEIPT_SCAN = "receipt_scan"
    MEAL_PLAN = "meal_plan"
    WORKOUT_PLAN = "workout_plan"


# Free allowance per local day. None = no limit. Nothing is limited yet; the
# numbers belong here (one place) once the client has chosen them (decision D4).
FREE_DAILY_LIMITS: dict[Feature, int | None] = {feature: None for feature in Feature}


def require_feature(user_id: uuid.UUID, feature: Feature) -> None:
    """Raise when this person may not use [feature] right now. Allows everything today."""
    return None


def _new_session():
    # Looked up on each call, and a function of our own so tests can replace it
    # without touching get_db, which uses the same session maker.
    return database.async_session_maker()


async def record_usage(user_id: uuid.UUID, feature: Feature, day: date_type) -> None:
    """Count one successful use. Best effort: it must never fail the request.

    Runs after the response (a background task) with its own session, so it
    adds no time to the scan. Any error, such as the table not existing yet,
    is logged and dropped.
    """
    try:
        async with _new_session() as session:
            async with session.begin():
                async with session.begin_nested():
                    stmt = insert(AiUsage).values(user_id=user_id, day=day, feature=feature.value, count=1)
                    await session.execute(
                        stmt.on_conflict_do_update(
                            index_elements=[AiUsage.user_id, AiUsage.day, AiUsage.feature],
                            set_={"count": AiUsage.count + 1},
                        )
                    )
    except Exception:  # noqa: BLE001
        log.warning("ai usage not recorded for %s", feature.value, exc_info=True)
