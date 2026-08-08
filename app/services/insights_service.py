import json
from datetime import date as date_type, timedelta

import httpx
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.food_log import FoodLog
from app.models.target import Target

INSIGHTS_PROMPT_TEMPLATE = """You are a nutrition coach reviewing one user's food log.

Today's target: {calorie_target} kcal, {protein_target}g protein, {carbs_target}g carbs, {fat_target}g fat.
Today so far: {today_calories} kcal, {today_protein}g protein, {today_carbs}g carbs, {today_fat}g fat.

Last 7 days (date: calories/protein/carbs/fat):
{trend_lines}

Respond with ONLY a JSON object, no other text, in this exact shape:
{{"narrative": "2-3 sentence summary of how today and this week are going", "tips": ["short actionable tip", "short actionable tip", "short actionable tip"]}}"""


async def get_weekly_trend(db: AsyncSession, user_id: str) -> list[dict]:
    start = date_type.today() - timedelta(days=6)
    result = await db.execute(
        select(
            FoodLog.log_date,
            func.sum(FoodLog.calories).label("calories"),
            func.sum(FoodLog.protein_g).label("protein_g"),
            func.sum(FoodLog.carbs_g).label("carbs_g"),
            func.sum(FoodLog.fat_g).label("fat_g"),
        )
        .where(FoodLog.user_id == user_id, FoodLog.log_date >= start)
        .group_by(FoodLog.log_date)
    )
    by_date = {row.log_date: row for row in result.all()}

    trend = []
    for i in range(7):
        d = start + timedelta(days=i)
        row = by_date.get(d)
        trend.append(
            {
                "date": d.isoformat(),
                "calories": int(row.calories) if row and row.calories else 0,
                "protein_g": float(row.protein_g) if row and row.protein_g else 0,
                "carbs_g": float(row.carbs_g) if row and row.carbs_g else 0,
                "fat_g": float(row.fat_g) if row and row.fat_g else 0,
            }
        )
    return trend


async def generate_insights(db: AsyncSession, user_id: str, trend: list[dict]) -> dict:
    target_result = await db.execute(select(Target).where(Target.user_id == user_id))
    target = target_result.scalar_one_or_none()

    today_str = date_type.today().isoformat()
    today = next((t for t in trend if t["date"] == today_str), None) or {
        "calories": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0,
    }

    trend_lines = "\n".join(
        f"{t['date']}: {t['calories']} kcal, {t['protein_g']}g protein, "
        f"{t['carbs_g']}g carbs, {t['fat_g']}g fat"
        for t in trend
    )

    prompt = INSIGHTS_PROMPT_TEMPLATE.format(
        calorie_target=target.calorie_target if target else "not set",
        protein_target=target.protein_g if target else "not set",
        carbs_target=target.carbs_g if target else "not set",
        fat_target=target.fat_g if target else "not set",
        today_calories=today["calories"],
        today_protein=today["protein_g"],
        today_carbs=today["carbs_g"],
        today_fat=today["fat_g"],
        trend_lines=trend_lines,
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"response_mime_type": "application/json"},
    }
    url = f"{settings.gemini_base_url}/models/{settings.gemini_model}:generateContent"

    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            params={"key": settings.gemini_api_key},
            json=payload,
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()

    raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
    parsed = json.loads(raw_text)

    return {
        "narrative": parsed.get("narrative", ""),
        "tips": parsed.get("tips", []),
        "weekly_trend": trend,
    }