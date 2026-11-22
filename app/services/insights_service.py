import json
from datetime import date as date_type, timedelta

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.food_log import FoodLog
from app.i18n import LANGUAGE_NAMES, t
from app.i18n.dates import day_label
from app.models.target import Target
from app.services.gemini_client import generate_content

INSIGHTS_PROMPT_TEMPLATE = """You are a nutrition coach reviewing one user's food log.

Today's target: {calorie_target} kcal, {protein_target}g protein, {carbs_target}g carbs, {fat_target}g fat.
Today so far: {today_calories} kcal, {today_protein}g protein, {today_carbs}g carbs, {today_fat}g fat.

Last 7 days (date: calories/protein/carbs/fat):
{trend_lines}{movement_line}

Rules for any numbers you mention:
- Copy them exactly as given above. Never add, subtract, average or round them yourself, and never invent a figure.
- "Today so far" is the only figure for today; the app shows the same number on the home screen, so it must match.
- If today so far is 0 kcal, say nothing has been logged yet today.

Respond with ONLY a JSON object, no other text, in this exact shape:
{{"narrative": "2-3 sentence summary of how today and this week are going"}}{language_rule}"""

# Added only when they logged some movement this week, so the prompt is unchanged otherwise.
MOVEMENT_LINE = (
    "\n\nMovement this week (their own activity, only context): {minutes} min on {days} day(s). "
    "You may mention it in a few warm words. It never changes how much they should eat: never suggest eating more or "
    "less because of it, never give it a calorie value, and never say it burns or earns anything."
    "{eat_back}"
)
EAT_BACK_NOTE = " Today's target already includes {kcal} kcal from movement that they chose to add; use the target as given."

# Added only for a language other than English, so the English prompt is unchanged.
LANGUAGE_RULE = "\nWrite the narrative in {language}. Keep the JSON key as shown, and keep every number as given."


async def get_weekly_trend(db: AsyncSession, user_id: str, today: date_type) -> list[dict]:
    """Per-day totals for the 7 days ending on the user's [today]."""
    start = today - timedelta(days=6)
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


def _n(value) -> int:
    """A nutrition amount as the whole number the app shows."""
    try:
        return int(round(float(value or 0)))
    except (TypeError, ValueError):
        return 0


def _day_name(iso_day: str, lang: str) -> str:
    try:
        return day_label(date_type.fromisoformat(iso_day), lang)
    except (TypeError, ValueError):
        return str(iso_day)


async def generate_insights(
    db: AsyncSession, user_id: str, trend: list[dict], today: date_type, lang: str = "en", movement: dict | None = None
) -> dict:
    target_result = await db.execute(select(Target).where(Target.user_id == user_id))
    target = target_result.scalar_one_or_none()

    today_str = today.isoformat()
    today_totals = next((t for t in trend if t["date"] == today_str), None) or {
        "calories": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0,
    }

    # The model is told to copy these exactly, so they are written the way the
    # app shows them (whole grams, "Wed 18 Nov"), never as raw sums of floats
    # ("43.090999999999994g") or ISO dates.
    trend_lines = "\n".join(
        f"{_day_name(t['date'], lang)}: {_n(t['calories'])} kcal, {_n(t['protein_g'])}g protein, "
        f"{_n(t['carbs_g'])}g carbs, {_n(t['fat_g'])}g fat"
        for t in trend
    )

    prompt = INSIGHTS_PROMPT_TEMPLATE.format(
        calorie_target=(target.calorie_target + int((movement or {}).get("eat_back_kcal") or 0)) if target else "not set",
        protein_target=target.protein_g if target else "not set",
        carbs_target=target.carbs_g if target else "not set",
        fat_target=target.fat_g if target else "not set",
        today_calories=_n(today_totals["calories"]),
        today_protein=_n(today_totals["protein_g"]),
        today_carbs=_n(today_totals["carbs_g"]),
        today_fat=_n(today_totals["fat_g"]),
        trend_lines=trend_lines,
        movement_line=(
            MOVEMENT_LINE.format(
                minutes=int(movement.get("week_minutes", 0)),
                days=int(movement.get("active_days", 0)),
                eat_back=EAT_BACK_NOTE.format(kcal=int(movement["eat_back_kcal"])) if movement.get("eat_back_kcal") else "",
            )
            if movement and movement.get("week_minutes")
            else ""
        ),
        language_rule=LANGUAGE_RULE.format(language=LANGUAGE_NAMES[lang]) if lang in LANGUAGE_NAMES and lang != "en" else "",
    )

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"response_mime_type": "application/json"},
    }
    data = await generate_content(payload, kind="insights")

    candidates = data.get("candidates") or []
    if not candidates:
        raise RuntimeError("gemini returned no candidates for insights")
    parts = (candidates[0].get("content") or {}).get("parts") or []
    raw_text = "".join(p.get("text", "") for p in parts if p.get("text"))
    if not raw_text.strip():
        raise RuntimeError("gemini returned an empty insights response")
    parsed = json.loads(raw_text)

    return {
        "narrative": parsed.get("narrative") or "",
        # Tips were removed from the app. The field stays (empty) so a copy of
        # the app that is still open, or cached, does not break on a missing key.
        "tips": [],
        "weekly_trend": trend,
        "language": lang,  # so a cached answer is not served in another language
    }


FALLBACK_NARRATIVE = (
    "Your AI coach is taking a quick break — the analysis service is busy right "
    "now. Your week's trends are below; pull down to refresh in a moment for "
    "a fresh summary."
)


def degraded_insights(trend: list[dict], lang: str = "en") -> dict:
    """A usable payload when Gemini is unreachable.

    The weekly trend is computed from our own logs, so the chart still renders;
    only the AI narrative is replaced with an honest placeholder instead of
    failing the whole request with a 500.
    """
    return {
        "narrative": t(lang, FALLBACK_NARRATIVE),
        "tips": [],
        "weekly_trend": trend,
    }
