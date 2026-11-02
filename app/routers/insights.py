import logging
import uuid
from datetime import date as date_type, datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dates import resolve_today  # noqa: F401 - re-exported for tests
from app.core.security import get_current_user_id
from app.models.insights_cache import InsightsCache
from app.schemas.insights import InsightsOut
from app.services.insights_service import (
    degraded_insights,
    generate_insights,
    get_weekly_trend,
)

log = logging.getLogger("calorie_backend")

router = APIRouter(prefix="/insights", tags=["insights"])


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
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    today = resolve_today(date)

    result = await db.execute(
        select(InsightsCache).where(InsightsCache.user_id == user_id)
    )
    cached = result.scalar_one_or_none()
    if not refresh and cached and cached.date == today:
        return InsightsOut(
            **cached.payload, generated_at=_as_utc(cached.generated_at)
        )

    trend = await get_weekly_trend(db, user_id, today)
    try:
        payload = await generate_insights(db, user_id, trend, today)
    except Exception:  # noqa: BLE001 - the trend is still worth serving
        # Gemini being down (503 under load, or a timeout) must not take the
        # whole screen down. Serve last time's narrative if we have one and
        # always attach the freshly computed trend, which is local data.
        log.exception("insight generation failed; serving a degraded response")
        if cached and cached.payload:
            payload = dict(cached.payload)
            payload["weekly_trend"] = trend
            return InsightsOut(
                **payload, generated_at=_as_utc(cached.generated_at)
            )
        return InsightsOut(
            **degraded_insights(trend), generated_at=datetime.now(timezone.utc)
        )

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
