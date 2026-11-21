import logging
import uuid
from datetime import date as date_type, datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.dates import resolve_today  # noqa: F401 - re-exported for tests
from app.core.features import Feature, record_usage, require_feature
from app.core.language import get_language
from app.core.rate_limit import insight_generations
from app.core.security import get_current_user_id
from app.models.insights_cache import InsightsCache
from app.schemas.insights import InsightsOut
from app.services import gemini_budget
from app.services.insights_service import (
    degraded_insights,
    generate_insights,
    get_weekly_trend,
)

log = logging.getLogger("calorie_backend")

router = APIRouter(prefix="/insights", tags=["insights"])

class _NarrativeOff(Exception):
    """GEMINI_INSIGHTS=false: the AI paragraph is switched off."""


# How long a narrative is reused after the day's logs change underneath it.
NARRATIVE_MAX_AGE = timedelta(hours=3)


def _utcnow_naive() -> datetime:
    """UTC now with the tzinfo stripped.

    `insights_cache.generated_at` is a TIMESTAMP WITHOUT TIME ZONE, and asyncpg
    refuses to bind an aware datetime to one: "can't subtract offset-naive and
    offset-aware datetimes". Store naive UTC, which is what the column means.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _as_utc(value: datetime) -> datetime:
    """Normalise a value read back from that naive column so the API always
    reports an explicit UTC offset."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


@router.get("", response_model=InsightsOut)
async def get_insights(
    refresh: bool = False,
    date: date_type | None = None,
    background: BackgroundTasks = None,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
    lang: str = Depends(get_language),
):
    today = resolve_today(date)

    result = await db.execute(
        select(InsightsCache).where(InsightsCache.user_id == user_id)
    )
    cached = result.scalar_one_or_none()
    # The trend is our own data and cheap, so it is always computed fresh. The
    # narrative is a paid Gemini call, so it is only regenerated when there is
    # no cache for today, the person pulls to refresh, or the logs changed and
    # the cached text is at least NARRATIVE_MAX_AGE old. Before that, every
    # logged food caused a Gemini call (the app reloads after each change). In
    # between, the cached text is served with the live chart.
    trend = await get_weekly_trend(db, user_id, today)
    # A cached answer is in the language it was written in; another language
    # needs a fresh one (an old cache without the marker is English).
    same_language = bool(cached and cached.payload) and cached.payload.get("language", "en") == lang
    if not refresh and cached and cached.date == today and cached.payload and same_language:
        unchanged = cached.payload.get("weekly_trend") == trend
        age = _utcnow_naive() - _as_utc(cached.generated_at).replace(tzinfo=None)
        if unchanged or age < NARRATIVE_MAX_AGE:
            payload = dict(cached.payload)
            payload["weekly_trend"] = trend
            return InsightsOut(**payload, generated_at=_as_utc(cached.generated_at))

    try:
        # Each generation is a paid Gemini call, and `refresh=true` forces one.
        # Over the limit, fall through to the same degraded answer as an outage.
        if not settings.gemini_insights:
            raise _NarrativeOff()
        if not insight_generations.allow("insights", user_id):
            raise RuntimeError("insights rate limit reached")
        require_feature(user_id, Feature.INSIGHTS)
        payload = await generate_insights(db, user_id, trend, today, lang)
    except Exception as exc:  # noqa: BLE001 - the trend is still worth serving
        # Gemini being down (503 under load, or a timeout) must not take the
        # whole screen down. Serve last time's narrative if we have one and
        # always attach the freshly computed trend, which is local data.
        if isinstance(exc, _NarrativeOff) or gemini_budget.is_quota_error(exc):
            log.info("insight narrative not generated (switched off or quota spent); serving a degraded response")
        else:
            log.exception("insight generation failed; serving a degraded response")
        if cached and cached.payload and same_language:
            payload = dict(cached.payload)
            payload["weekly_trend"] = trend
            return InsightsOut(
                **payload, generated_at=_as_utc(cached.generated_at)
            )
        return InsightsOut(
            **degraded_insights(trend, lang), generated_at=datetime.now(timezone.utc)
        )

    # Counted only for a real generation (cache hits cost nothing), after the
    # response, so the free limit can later be chosen from real numbers.
    if background is not None:
        background.add_task(record_usage, user_id, Feature.INSIGHTS, today)

    now = datetime.now(timezone.utc)
    try:
        stmt = pg_insert(InsightsCache).values(
            user_id=user_id,
            date=today,
            payload=payload,
            generated_at=_utcnow_naive(),
        ).on_conflict_do_update(
            index_elements=["user_id"],
            set_={"date": today, "payload": payload, "generated_at": _utcnow_naive()},
        )
        await db.execute(stmt)
        await db.commit()
    except Exception:  # noqa: BLE001 - caching is best-effort
        # The insights are already generated; a full cache or a write error
        # should not turn a successful analysis into a 500.
        await db.rollback()
        log.exception("failed to cache insights; returning the fresh result")

    return InsightsOut(**payload, generated_at=now)
