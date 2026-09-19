"""SRS endpoints: обзор, очередь, enrollment, настройки, reviews, undo, reset."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.errors import ApiError
from app.models import Card, SetModel, SrsEnrollment, SrsReview, SrsState, User
from app.services.access import visible_sets_condition
from app.services import srs_service
from app.srs import adapter as fsrs

router = APIRouter(prefix="/srs", tags=["srs"])


class EnrollIn(BaseModel):
    set_id: str
    enabled: bool = True
    forward_enabled: bool = True
    reverse_enabled: bool = False


class ReviewIn(BaseModel):
    card_id: str
    direction: str
    rating: str
    expected_state_version: int | None = Field(default=None, ge=0)
    content_version: int | None = Field(default=None, ge=1)
    client_event_id: str = Field(min_length=8, max_length=64)
    session_id: str | None = None


class ResetIn(BaseModel):
    set_id: str
    directions: list[str] = Field(default_factory=lambda: ["front_to_back", "back_to_front"])


class SuspendedIn(BaseModel):
    suspended: bool


@router.get("/overview")
async def overview(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await srs_service.overview(db, user)


@router.get("/queue")
async def queue(
    limit: int | None = None, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    items = await srs_service.queue(db, user, limit)
    out = []
    for it in items:
        card = (
            await db.execute(select(Card).where(Card.id == it["card_id"]))
        ).scalar_one()
        direction = it["direction"]
        question = card.front_text if direction == "front_to_back" else card.back_text
        answer = card.back_text if direction == "front_to_back" else card.front_text
        hint = card.front_hint if direction == "front_to_back" else card.back_hint
        context = card.front_context if direction == "front_to_back" else card.back_context
        out.append(
            {
                **{k: v for k, v in it.items() if k != "card"},
                "question_text": question,
                "answer_text": answer,
                "hint": hint,
                "context": context,
            }
        )
    return {"items": out}


@router.post("/enroll")
async def enroll(payload: EnrollIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await srs_service.enroll(
        db, user, payload.set_id, payload.enabled, payload.forward_enabled, payload.reverse_enabled
    )


@router.get("/enrollments")
async def enrollments(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (
        await db.execute(
            select(SrsEnrollment)
            .join(SetModel, SetModel.id == SrsEnrollment.set_id)
            .where(
                SrsEnrollment.user_id == user.id,
                SetModel.deleted_at.is_(None),
                visible_sets_condition(user),
            )
        )
    ).scalars().all()
    return [
        {
            "set_id": r.set_id, "enabled": r.enabled,
            "forward_enabled": r.forward_enabled, "reverse_enabled": r.reverse_enabled,
        }
        for r in rows
    ]


@router.patch("/settings")
async def patch_settings(
    payload: dict, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    row = await srs_service.get_srs_settings(db, user.id)
    if "desired_retention" in payload:
        value = float(payload["desired_retention"])
        if not 0.80 <= value <= 0.97:
            raise ApiError(422, "VALIDATION_ERROR", "Целевая вероятность: от 0.80 до 0.97.")
        row.desired_retention = value
    if "new_per_day" in payload:
        value = int(payload["new_per_day"])
        if not 0 <= value <= 200:
            raise ApiError(422, "VALIDATION_ERROR", "Лимит новых: от 0 до 200.")
        row.new_per_day = value
    if "round_size" in payload:
        value = int(payload["round_size"])
        if not 5 <= value <= 100:
            raise ApiError(422, "VALIDATION_ERROR", "Размер раунда: от 5 до 100.")
        row.round_size = value
    await db.commit()
    return {
        "desired_retention": row.desired_retention,
        "new_per_day": row.new_per_day,
        "round_size": row.round_size,
    }


@router.post("/reviews")
async def submit_review(payload: ReviewIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await srs_service.submit_review(
        db, user, payload.card_id, payload.direction, payload.rating,
        payload.expected_state_version, payload.content_version,
        payload.client_event_id, payload.session_id,
    )


@router.post("/reviews/preview")
async def preview_intervals(
    payload: dict, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    card_id = payload.get("card_id")
    direction = payload.get("direction")
    if not card_id or direction not in ("front_to_back", "back_to_front"):
        raise ApiError(422, "VALIDATION_ERROR", "Нужны card_id и direction.")
    state = (
        await db.execute(
            select(SrsState).where(
                SrsState.user_id == user.id, SrsState.card_id == card_id, SrsState.direction == direction
            )
        )
    ).scalar_one_or_none()
    settings_row = await srs_service.get_srs_settings(db, user.id)
    cfg = srs_service.scheduler_config(settings_row)
    payload_fsrs = json.loads(state.scheduler_payload) if state else fsrs.new_payload()
    return {"intervals": fsrs.preview_intervals(payload_fsrs, cfg), "is_new": state is None}


@router.post("/reviews/{review_id}/undo")
async def undo_review(
    review_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    return await srs_service.undo_last_review(db, user, review_id)


@router.post("/reset")
async def reset(payload: ResetIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    from app.services.access import get_set_access

    await get_set_access(db, user, payload.set_id)
    cards = (
        await db.execute(select(Card.id).where(Card.set_id == payload.set_id, Card.deleted_at.is_(None)))
    ).scalars().all()
    affected = await srs_service.reset_progress(db, user, list(cards), payload.directions)
    return {"ok": True, "affected": affected}


@router.put("/states/{state_id}/suspended")
async def set_suspended(
    state_id: str, payload: SuspendedIn, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    state = (
        await db.execute(
            select(SrsState).where(SrsState.id == state_id, SrsState.user_id == user.id)
        )
    ).scalar_one_or_none()
    if state is None:
        raise ApiError(404, "NOT_FOUND", "Состояние не найдено.")
    state.suspended = payload.suspended
    await db.commit()
    return {"ok": True, "suspended": state.suspended}


@router.get("/history")
async def history(
    limit: int = 50, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    rows = (
        await db.execute(
            select(SrsReview)
            .where(SrsReview.user_id == user.id)
            .order_by(SrsReview.reviewed_at.desc())
            .limit(min(limit, 200))
        )
    ).scalars().all()
    return [
        {
            "id": r.id, "card_id": r.card_id, "direction": r.direction,
            "rating": {1: "again", 2: "hard", 3: "good", 4: "easy"}.get(r.rating),
            "due_before": r.before_due_at, "due_after": r.after_due_at,
            "reviewed_at": r.reviewed_at, "undone_at": r.undone_at, "is_undo": r.is_undo_event,
        }
        for r in rows
    ]
