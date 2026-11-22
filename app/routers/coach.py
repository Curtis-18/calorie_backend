"""The AI coach: a pinned chat in Messages (roadmap R8.4, step 4a).

Text only. The coach is not a person and not a user, so its history lives in
its own table. What it is told about the person is built here, on the server,
from their own data; the app never sends it. Adults only: the plan (targets)
already refuses under 18, and the coach needs a plan to know the calorie floor.
"""

import logging
import uuid
from datetime import date as date_type, datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dates import resolve_today
from app.core.features import Feature, record_usage, require_feature
from app.core.language import get_language
from app.core.rate_limit import coach_turns
from app.core.security import get_current_user_id
from app.models.coach_message import CoachMessage
from app.models.food_log import FoodLog
from app.models.recipe import Recipe
from app.models.target import Target
from app.models.user_prefs import UserPrefs
from app.routers.budget import _load_prefs as load_budget_prefs
from app.services import coach_prompt, coach_service, meal_swaps, movement_read, workouts
from app.services.insights_service import get_weekly_trend
from app.services.regions import region_label
from app.services.target_calculator import MIN_CALORIES
from app.services.week_budget import compute_week_budget, week_start_of

log = logging.getLogger("calorie_backend")

router = APIRouter(prefix="/coach", tags=["coach"])

PAGE = 50
RETENTION_DAYS = 90
MAX_TEXT = 1000
UNAVAILABLE = "The coach isn't available right now. Please try again in a moment."


class CoachMessageIn(BaseModel):
    id: uuid.UUID
    text: str = Field(min_length=1, max_length=MAX_TEXT)

    @field_validator("text")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Write something first.")
        return v


class CoachSuggestion(BaseModel):
    """One of the person's own recipes the coach named, with its numbers per
    serving read from the database (never from the model's words)."""

    recipe_id: uuid.UUID
    title: str
    calories: int
    protein_g: int
    carbs_g: int
    fat_g: int


class WorkoutStep(BaseModel):
    name: str
    cue: str
    amount: str


class WorkoutSection(BaseModel):
    title: str
    repeat: str | None = None
    steps: list[WorkoutStep]


class CoachWorkout(BaseModel):
    """A routine from the curated library (services/workouts.py), written in the
    person's language. The coach only names it; it never writes the moves."""

    id: str
    name: str
    duration: str
    focus: str
    summary: str
    sections: list[WorkoutSection]
    safety: str


class CoachMessageOut(BaseModel):
    id: uuid.UUID
    role: str
    body: str
    created_at: datetime
    # Only on the answer just given. They are not stored, so a reloaded thread
    # shows the same words without the buttons.
    suggestions: list[CoachSuggestion] = []
    workouts: list[CoachWorkout] = []


class CoachThreadOut(BaseModel):
    messages: list[CoachMessageOut]
    has_more: bool = False


def _out(
    m: CoachMessage, suggestions: list[dict] | None = None, routines: list[dict] | None = None
) -> CoachMessageOut:
    return CoachMessageOut(
        id=m.id, role=m.role, body=m.body, created_at=m.created_at, workouts=routines or [],
        suggestions=[
            CoachSuggestion(
                recipe_id=r["id"], title=r["title"], calories=r["calories"],
                protein_g=r["protein_g"], carbs_g=r["carbs_g"], fat_g=r["fat_g"],
            )
            for r in suggestions or []
        ],
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _target(db: AsyncSession, user_id: uuid.UUID) -> Target:
    target = (await db.execute(select(Target).where(Target.user_id == user_id))).scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="Finish setting up your plan first")
    return target


async def _build_context(
    db: AsyncSession, user_id: uuid.UUID, target: Target, today: date_type, lang: str = "en"
) -> tuple[str, list[dict]]:
    """The text the coach is told, and the person's recipes (with ids) that the
    answer may name."""
    floor = MIN_CALORIES[target.sex]
    entries = (
        await db.execute(
            select(FoodLog).where(FoodLog.user_id == user_id, FoodLog.log_date == today).order_by(FoodLog.timestamp)
        )
    ).scalars().all()
    totals = {
        "calories": sum(e.calories or 0 for e in entries),
        "protein_g": sum(e.protein_g or 0 for e in entries),
        "carbs_g": sum(e.carbs_g or 0 for e in entries),
        "fat_g": sum(e.fat_g or 0 for e in entries),
    }
    week = await get_weekly_trend(db, user_id, today)

    # Today's allowance follows the weekly plan when the person turned it on.
    allowance = None
    prefs = await load_budget_prefs(db, user_id)
    if prefs["mode"] == "weekly":
        start = week_start_of(today, prefs["week_start_day"])
        rows = (
            await db.execute(
                select(FoodLog.log_date, func.sum(FoodLog.calories))
                .where(FoodLog.user_id == user_id, FoodLog.log_date >= start, FoodLog.log_date <= today)
                .group_by(FoodLog.log_date)
            )
        ).all()
        built = compute_week_budget(
            today=today, target=target.calorie_target, floor=floor,
            eaten_by_date={d: int(total or 0) for d, total in rows},
            start_day=prefs["week_start_day"], weights=prefs["weights"],
        )
        allowance = built.today.allowance

    region = None
    recipes: list[dict] = []
    try:
        async with db.begin_nested():
            row = (await db.execute(select(UserPrefs.region).where(UserPrefs.user_id == user_id))).scalar_one_or_none()
            region = region_label(row)
            found = (
                await db.execute(
                    select(Recipe)
                    .where(Recipe.owner_id == user_id, Recipe.deleted_at.is_(None))
                    .order_by(Recipe.updated_at.desc())
                    .limit(20)
                )
            ).scalars().all()
            recipes = [
                {"id": r.id, "title": r.title, "calories": r.calories_per_serving, "protein_g": round(r.protein_g or 0),
                 "carbs_g": round(r.carbs_g or 0), "fat_g": round(r.fat_g or 0)}
                for r in found
            ]
    except Exception:  # noqa: BLE001
        log.warning("coach context: region or recipes unavailable", exc_info=True)

    moved = await movement_read.week_snapshot(db, user_id, today)
    if moved["eat_back_kcal"]:
        # The person chose to add a share of today's movement to the plan; the ring shows it too.
        allowance = (allowance or target.calorie_target) + moved["eat_back_kcal"]

    left_kcal = max(0, (allowance or target.calorie_target) - int(totals["calories"]))
    left_protein = max(0, target.protein_g - round(totals["protein_g"]))
    best_fits = meal_swaps.rank_fits(recipes, left_kcal, left_protein)

    context = coach_prompt.build_context(
        goal=target.goal, calorie_target=target.calorie_target, floor=floor,
        protein_g=target.protein_g, carbs_g=target.carbs_g, fat_g=target.fat_g,
        today_entries=[
            {"name": e.name, "meal": e.meal_type, "calories": e.calories, "protein_g": round(e.protein_g or 0)}
            for e in entries
        ],
        today_totals=totals, allowance_today=allowance, week=week, region=region, recipes=recipes,
        best_fits=best_fits, routines=workouts.names(lang), movement=moved,
    )
    return context, recipes


async def _history(db: AsyncSession, user_id: uuid.UUID, before_id: uuid.UUID) -> list[tuple[str, str]]:
    rows = (
        await db.execute(
            select(CoachMessage.role, CoachMessage.body)
            .where(CoachMessage.user_id == user_id, CoachMessage.id != before_id)
            .order_by(CoachMessage.created_at.desc())
            .limit(coach_service.HISTORY_TURNS)
        )
    ).all()
    return [(r, b) for r, b in reversed(rows)]


@router.post("/messages", response_model=CoachMessageOut)
async def send_message(
    data: CoachMessageIn,
    background: BackgroundTasks,
    date: date_type | None = None,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
    lang: str = Depends(get_language),
):
    """Store the person's turn, answer it, store and return the answer.

    Idempotent on `id`: sending the same turn again returns the stored answer,
    or answers it now if the first attempt never got that far.
    """
    require_feature(user_id, Feature.COACH_CHAT)
    today = resolve_today(date)
    target = await _target(db, user_id)

    try:
        async with db.begin_nested():
            existing = (await db.execute(select(CoachMessage).where(CoachMessage.id == data.id))).scalar_one_or_none()
            if existing is not None and (existing.user_id != user_id or existing.role != "user"):
                raise HTTPException(status_code=409, detail="That message id is already used.")
            answered = None
            if existing is not None:
                answered = (
                    await db.execute(
                        select(CoachMessage)
                        .where(
                            CoachMessage.user_id == user_id,
                            CoachMessage.role == "coach",
                            CoachMessage.created_at > existing.created_at,
                        )
                        .order_by(CoachMessage.created_at)
                        .limit(1)
                    )
                ).scalar_one_or_none()
            if answered is None and existing is None:
                coach_turns.check("coach", user_id, "You're sending a lot of messages. Give it a few minutes.")
                db.add(CoachMessage(id=data.id, user_id=user_id, role="user", body=data.text))
                await db.flush()
            elif answered is None:
                coach_turns.check("coach", user_id, "You're sending a lot of messages. Give it a few minutes.")
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        log.warning("coach turn not stored: %r", exc)
        await db.rollback()
        raise HTTPException(status_code=503, detail=UNAVAILABLE)
    if answered is not None:
        return _out(answered)
    await db.commit()

    floor = MIN_CALORIES[target.sex]
    from_model = False
    recipes: list[dict] = []
    tokens_in = tokens_out = None
    if coach_prompt.needs_care(data.text):
        log.info("coach_care_reply")
        reply = coach_service.care_reply(lang)
    else:
        context, recipes = await _build_context(db, user_id, target, today, lang)
        history = await _history(db, user_id, data.id)
        try:
            reply, tokens_in, tokens_out, from_model = await coach_service.reply_to(
                context=context, history=history, text=data.text, lang=lang, floor=floor
            )
        except coach_service.CoachUnavailable:
            raise HTTPException(status_code=503, detail=UNAVAILABLE)

    stored = CoachMessage(
        id=uuid.uuid4(), user_id=user_id, role="coach", body=reply, tokens_in=tokens_in, tokens_out=tokens_out
    )
    try:
        async with db.begin_nested():
            db.add(stored)
            await db.flush()
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        log.warning("coach reply not stored: %r", exc)
        await db.rollback()
        raise HTTPException(status_code=503, detail=UNAVAILABLE)
    await db.refresh(stored)
    if from_model:
        background.add_task(record_usage, user_id, Feature.COACH_CHAT, today)
    await _forget_old(db, user_id)
    # Buttons only for an answer the model wrote, and only for recipes it named.
    named = meal_swaps.named_in(reply, recipes) if from_model else []
    # One routine at most, and only one whose exact name the reply uses.
    routine = meal_swaps.named_in(reply, workouts.names(lang), limit=1) if from_model else []
    return _out(stored, named, [workouts.render(workouts.get(r["id"]), lang) for r in routine])


async def _forget_old(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Keep 90 days of history. Best effort, after the answer is stored."""
    try:
        async with db.begin_nested():
            await db.execute(
                delete(CoachMessage).where(
                    CoachMessage.user_id == user_id, CoachMessage.created_at < _now() - timedelta(days=RETENTION_DAYS)
                )
            )
        await db.commit()
    except Exception:  # noqa: BLE001
        log.warning("coach history cleanup skipped", exc_info=True)


@router.get("/messages", response_model=CoachThreadOut)
async def get_messages(
    before: datetime | None = None,
    limit: int = Query(PAGE, ge=1, le=100),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """The newest page, oldest first. Pass `before` (the first message's
    created_at) for the page before it. An empty thread if the table is
    missing, so the app just shows the greeting."""
    query = select(CoachMessage).where(CoachMessage.user_id == user_id)
    if before is not None:
        query = query.where(CoachMessage.created_at < before)
    try:
        async with db.begin_nested():
            rows = (await db.execute(query.order_by(CoachMessage.created_at.desc()).limit(limit + 1))).scalars().all()
    except Exception:  # noqa: BLE001
        log.warning("coach history unavailable", exc_info=True)
        return CoachThreadOut(messages=[])
    return CoachThreadOut(messages=[_out(m) for m in reversed(rows[:limit])], has_more=len(rows) > limit)


@router.delete("/messages", status_code=204)
async def clear_messages(user_id: uuid.UUID = Depends(get_current_user_id), db: AsyncSession = Depends(get_db)):
    """"Clear conversation": removes the person's whole history with the coach."""
    try:
        async with db.begin_nested():
            await db.execute(delete(CoachMessage).where(CoachMessage.user_id == user_id))
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        log.warning("coach history not cleared: %r", exc)
        await db.rollback()
        raise HTTPException(status_code=503, detail="Couldn't clear that right now.")
