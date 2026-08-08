from datetime import date as date_type, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user_id
from app.models.insights_cache import InsightsCache
from app.schemas.insights import InsightsOut
from app.services.insights_service import generate_insights, get_weekly_trend

router = APIRouter(prefix="/insights", tags=["insights"])


@router.get("", response_model=InsightsOut)
async def get_insights(
    refresh: bool = False,
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    today = date_type.today()

    if not refresh:
        result = await db.execute(
            select(InsightsCache).where(InsightsCache.user_id == user_id)
        )
        cached = result.scalar_one_or_none()
        if cached and cached.date == today:
            return InsightsOut(**cached.payload, generated_at=cached.generated_at)

    trend = await get_weekly_trend(db, user_id)
    payload = await generate_insights(db, user_id, trend)

    now = datetime.utcnow()
    stmt = pg_insert(InsightsCache).values(
        user_id=user_id, date=today, payload=payload, generated_at=now
    ).on_conflict_do_update(
        index_elements=["user_id"],
        set_={"date": today, "payload": payload, "generated_at": now},
    )
    await db.execute(stmt)
    await db.commit()

    return InsightsOut(**payload, generated_at=now)