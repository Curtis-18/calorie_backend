import logging
import uuid
from datetime import date as date_type, datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
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


@router.get("", response_model=InsightsOut)
async def get_insights(
    refresh: bool = False,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    today = date_type.today()

    result = await db.execute(
        select(InsightsCache).where(InsightsCache.user_id == user_id)
    )
    cached = result.scalar_one_or_none()
    if not refresh and cached and cached.date == today:
        return InsightsOut(**cached.payload, generated_at=cached.generated_at)

    trend = await get_weekly_trend(db, user_id)
    try:
        payload = await generate_insights(db, user_id, trend)
    except Exception:  # noqa: BLE001 - the trend is still worth serving
        # Gemini being down (503 under load, or a timeout) must not take the
        # whole screen down. Serve last time's narrative if we have one and
        # always attach the freshly computed trend, which is local data.
        log.exception("insight generation failed; serving a degraded response")
        if cached and cached.payload:
            payload = dict(cached.payload)
            payload["weekly_trend"] = trend
            return InsightsOut(**payload, generated_at=cached.generated_at)
        return InsightsOut(
            **degraded_insights(trend), generated_at=datetime.now(timezone.utc)
        )

    now = datetime.now(timezone.utc)
    stmt = pg_insert(InsightsCache).values(
        user_id=user_id, date=today, payload=payload, generated_at=now
    ).on_conflict_do_update(
        index_elements=["user_id"],
        set_={"date": today, "payload": payload, "generated_at": now},
    )
    await db.execute(stmt)
    await db.commit()

    return InsightsOut(**payload, generated_at=now)
