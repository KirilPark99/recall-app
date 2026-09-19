"""Статистика: сводка, активность по дням, по наборам, слабые карточки, цели."""
from __future__ import annotations

import json
from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.db.base import utcnow
from app.models import (
    ActivityEvent, DailyGoal, SrsReview, StudyAnswer, StudySessionItem, TestAttempt, User,
    UserPreferences, SrsState,
)
from app.services.local_dates import local_date_for

router = APIRouter(prefix="/stats", tags=["stats"])


async def _get_goal(db: AsyncSession, user: User, local_date: str) -> dict:
    prefs = (
        await db.execute(select(UserPreferences).where(UserPreferences.user_id == user.id))
    ).scalar_one_or_none()
    goal = (
        await db.execute(
            select(DailyGoal).where(DailyGoal.user_id == user.id, DailyGoal.local_date == local_date)
        )
    ).scalar_one_or_none()
    target_reviews = goal.target_reviews if goal else (prefs.daily_goal_reviews if prefs else 20)
    target_minutes = goal.target_minutes if goal else (prefs.daily_goal_minutes if prefs else 15)
    enabled = goal.enabled if goal else bool(prefs and prefs.goals_enabled)
    reviews_done = (
        await db.execute(
            select(func.count()).select_from(ActivityEvent).where(
                ActivityEvent.user_id == user.id,
                ActivityEvent.local_date == local_date,
                ActivityEvent.event_type == "srs_review",
            )
        )
    ).scalar_one()
    from sqlalchemy import text as sqltext

    minutes_done = (
        await db.execute(
            sqltext(
                "SELECT COALESCE(SUM(CAST(json_extract(meta_json, '$.minutes') AS INTEGER)), 0) "
                "FROM activity_events WHERE user_id = :uid AND local_date = :d AND event_type = 'study_minutes'"
            ),
            {"uid": user.id, "d": local_date},
        )
    ).scalar_one()
    return {
        "local_date": local_date,
        "enabled": enabled,
        "target_reviews": target_reviews,
        "target_minutes": target_minutes,
        "reviews_done": reviews_done,
        "minutes_done": minutes_done,
    }


@router.get("/summary")
async def summary(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    today = local_date_for(user.timezone)
    goal = await _get_goal(db, user, today)
    srs = await srs_overview(db, user)
    # Серия дней (с оговоркой о часовом поясе — считается по local_date).
    streak = 0
    dates = set(
        (
            await db.execute(
                select(ActivityEvent.local_date).where(
                    ActivityEvent.user_id == user.id,
                    ActivityEvent.event_type.in_(("srs_review", "study_minutes")),
                )
            )
        ).scalars()
    )
    from datetime import date

    cursor = date.fromisoformat(today)
    while cursor.isoformat() in dates:
        streak += 1
        cursor -= timedelta(days=1)
    return {"goal": goal, "srs": srs, "streak_days": streak, "streak_note": "по локальной дате пользователя"}


async def srs_overview(db: AsyncSession, user: User):
    from app.services.srs_service import overview as srs_ov

    return await srs_ov(db, user)


@router.get("/activity")
async def activity(
    days: int = Query(default=30, ge=7, le=365),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = (
        await db.execute(
            select(ActivityEvent.local_date, ActivityEvent.event_type, func.count())
            .where(
                ActivityEvent.user_id == user.id,
                ActivityEvent.occurred_at_utc >= utcnow() - timedelta(days=days),
            )
            .group_by(ActivityEvent.local_date, ActivityEvent.event_type)
            .order_by(ActivityEvent.local_date)
        )
    ).all()
    by_date: dict[str, dict] = {}
    for local_date, event_type, count in rows:
        by_date.setdefault(local_date, {"date": local_date, "srs_reviews": 0, "study_answers": 0, "sessions": 0, "minutes": 0})
        key = {"srs_review": "srs_reviews", "study_answer": "study_answers", "session_completed": "sessions", "study_minutes": "minutes"}.get(event_type)
        if key:
            if key == "minutes":
                continue
            by_date[local_date][key] = count
    minute_rows = (
        await db.execute(
            select(ActivityEvent.local_date, ActivityEvent.meta_json).where(
                ActivityEvent.user_id == user.id,
                ActivityEvent.event_type == "study_minutes",
                ActivityEvent.occurred_at_utc >= utcnow() - timedelta(days=days),
            )
        )
    ).all()
    for local_date, meta_json in minute_rows:
        by_date.setdefault(local_date, {"date": local_date, "srs_reviews": 0, "study_answers": 0, "sessions": 0, "minutes": 0})
        by_date[local_date]["minutes"] += int(json.loads(meta_json or "{}").get("minutes", 0))
    # Дни без данных не рисуем нулями — клиент покажет пропуск.
    return {"days": sorted(by_date.values(), key=lambda d: d["date"])}


@router.get("/sets/{set_id}")
async def set_stats(
    set_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    from app.models import Card
    from app.services.access import get_set_access

    await get_set_access(db, user, set_id)
    answers = (
        await db.execute(
            select(StudyAnswer.final_correct, func.count())
            .join(StudySessionItem, StudySessionItem.id == StudyAnswer.item_id)
            .join(Card, Card.id == StudySessionItem.card_id)
            .where(StudyAnswer.user_id == user.id, Card.set_id == set_id)
            .group_by(StudyAnswer.final_correct)
        )
    ).all()
    correct = dict((bool(k), v) for k, v in answers)
    states = (
        await db.execute(
            select(SrsState.direction, func.count())
            .where(SrsState.user_id == user.id)
            .join(Card, Card.id == SrsState.card_id)
            .where(Card.set_id == set_id)
            .group_by(SrsState.direction)
        )
    ).all()
    reviews = (
        await db.execute(
            select(func.count())
            .select_from(SrsReview)
            .join(Card, Card.id == SrsReview.card_id)
            .where(SrsReview.user_id == user.id, Card.set_id == set_id, SrsReview.is_undo_event.is_(False))
        )
    ).scalar_one()
    return {
        "answers_correct": correct.get(True, 0),
        "answers_incorrect": correct.get(False, 0),
        "srs_reviews": reviews,
        "srs_by_direction": {d: c for d, c in states},
    }


@router.get("/weak-cards")
async def weak_cards(
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.models import StudySession

    rows = (
        await db.execute(
            select(
                StudySessionItem.card_id,
                StudySessionItem.direction,
                StudySessionItem.snapshot_json,
                StudySessionItem.answer_key_json,
                func.count(),
            )
            .join(StudyAnswer, StudyAnswer.item_id == StudySessionItem.id)
            .join(StudySession, StudySession.id == StudySessionItem.session_id)
            .where(
                StudyAnswer.user_id == user.id,
                StudyAnswer.final_correct.is_(False),
                StudySession.mode.in_(("write", "learn", "spell", "test")),
            )
            .group_by(StudySessionItem.card_id)
            .order_by(func.count().desc())
            .limit(limit)
        )
    ).all()
    out = []
    for card_id, direction, snapshot_json, answer_key_json, count in rows:
        snapshot = json.loads(snapshot_json or "{}")
        answer_key = json.loads(answer_key_json or "{}")
        question = snapshot.get("question_text", "")
        answer = answer_key.get("correct_text", "")
        if not question and not answer:
            continue
        if direction == "back_to_front":
            question, answer = answer, question
        out.append({"card_id": card_id, "front_text": question, "back_text": answer, "mistakes": count})
    return {"items": out}


@router.get("/tests")
async def test_history(
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    rows = (
        await db.execute(
            select(TestAttempt)
            .where(TestAttempt.user_id == user.id)
            .order_by(TestAttempt.finished_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [
        {
            "session_id": a.session_id,
            "score": a.score,
            "max_score": a.max_score,
            "percent": round(a.score * 100 / a.max_score) if a.max_score else None,
            "finished_at": a.finished_at,
        }
        for a in rows
    ]
