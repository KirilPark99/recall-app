"""Занятия: создание, задания, ответы, черновики, завершение, результаты."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.config import settings
from app.core.errors import ApiError
from app.db.base import new_uuid, utcnow
from app.models import (
    ActivityEvent, StudyAnswer, StudySession, StudySessionItem, TestAttempt, User,
)
from app.services import learn as learn_algo
from app.services import questions as qgen
from app.services.study_service import (
    StudyService, deserialize_entry, item_snapshot,
)

router = APIRouter(tags=["study"])


class SessionCreate(BaseModel):
    mode: str
    set_ids: list[str] | None = None
    folder_id: str | None = None
    direction: str = "front_to_back"
    card_filter: str = "all"
    limit: int = Field(default=0, ge=0, le=5000)
    order: str = "random"
    settings: dict = Field(default_factory=dict)


class AnswerIn(BaseModel):
    item_id: str
    client_event_id: str = Field(min_length=8, max_length=64)
    answer: dict = Field(default_factory=dict)
    latency_ms: int | None = Field(default=None, ge=0, le=10 * 60 * 1000)


class DraftIn(BaseModel):
    draft: str | None = Field(default=None, max_length=10000)
    draft_version: int = Field(ge=0)


class ProgressIn(BaseModel):
    current_index: int | None = Field(default=None, ge=0)
    active_ms_delta: int = Field(default=0, ge=0, le=180000)


class MatchMoveIn(BaseModel):
    first_item_id: str | None = None
    second_item_id: str | None = None


@router.post("/study-sessions", status_code=201)
async def create_session(
    payload: SessionCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    svc = StudyService(db, user)
    sp = dict(payload.settings)
    direction = payload.direction
    if payload.mode == "test":
        sp["direction"] = direction
    session = await svc.create_session(
        mode=payload.mode,
        set_ids=payload.set_ids,
        folder_id=payload.folder_id,
        direction=direction,
        card_filter=payload.card_filter,
        limit=payload.limit,
        order=payload.order,
        settings_payload=sp,
    )
    return await session_dto(db, session, include_items=True)


@router.get("/study-sessions")
async def list_sessions(
    limit: int = 10, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    rows = (
        await db.execute(
            select(StudySession)
            .where(StudySession.user_id == user.id)
            .order_by(StudySession.last_activity_at.desc())
            .limit(min(limit, 50))
        )
    ).scalars().all()
    return [
        {
            "id": s.id,
            "mode": s.mode,
            "status": s.status,
            "started_at": s.started_at,
            "completed_at": s.completed_at,
            "current_index": s.current_index,
            "item_count": len(json.loads(s.pool_json)),
        }
        for s in rows
    ]


@router.get("/study-sessions/{session_id}")
async def get_session(
    session_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    svc = StudyService(db, user)
    session = await svc.get_session(session_id)
    return await session_dto(db, session, include_items=True)


@router.patch("/study-sessions/{session_id}/pause")
async def pause_session(
    session_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    svc = StudyService(db, user)
    session = await svc.get_session(session_id)
    if session.status == "active":
        session.status = "paused"
        await db.commit()
    return {"ok": True, "status": session.status}


@router.patch("/study-sessions/{session_id}/resume")
async def resume_session(
    session_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    svc = StudyService(db, user)
    session = await svc.get_session(session_id)
    if session.status == "paused":
        session.status = "active"
        session.last_activity_at = utcnow()
        await db.commit()
    return {"ok": True, "status": session.status}


@router.patch("/study-sessions/{session_id}/progress")
async def progress(
    session_id: str,
    payload: ProgressIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    svc = StudyService(db, user)
    session = await svc.get_session(session_id)
    if payload.active_ms_delta > 0:
        # Ограничение длины одного интервала активности — оценка, а не измерение.
        session.active_ms += min(payload.active_ms_delta, 120000)
    if payload.current_index is not None:
        session.current_index = max(session.current_index, payload.current_index)
    session.last_activity_at = utcnow()
    await db.commit()
    return {"ok": True, "active_ms": session.active_ms}


@router.get("/study-sessions/{session_id}/items/{item_id}")
async def get_task(
    session_id: str,
    item_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    svc = StudyService(db, user)
    session = await svc.get_session(session_id)
    item = await svc.get_item(session, item_id)
    return task_dto(item, session)


@router.post("/study-sessions/{session_id}/answers")
async def submit_answer(
    session_id: str,
    payload: AnswerIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    svc = StudyService(db, user)
    session = await svc.get_session(session_id)
    feedback = await svc.submit_answer(
        session, payload.item_id, payload.client_event_id, payload.answer, payload.latency_ms
    )
    return feedback


@router.post("/study-sessions/{session_id}/items/{item_id}/skip")
async def skip_item(
    session_id: str,
    item_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    svc = StudyService(db, user)
    session = await svc.get_session(session_id)
    item = await svc.get_item(session, item_id)
    await svc.require_active(session)
    item.skipped = True
    item.status = "skipped"
    session.last_activity_at = utcnow()
    if session.mode == "learn":
        key = f"{item.card_id}:{item.direction}"
        ls = learn_algo._lstate(session)
        if key in ls["queue"]:
            ls["queue"].remove(key)
        ls["queue"].append(key)
        learn_algo._save(session, ls)
    await db.commit()
    return {"ok": True}


@router.post("/study-sessions/{session_id}/items/{item_id}/reveal")
async def reveal_item(
    session_id: str,
    item_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    svc = StudyService(db, user)
    session = await svc.get_session(session_id)
    item = await svc.get_item(session, item_id)
    await svc.require_active(session)
    item.revealed = True
    session.last_activity_at = utcnow()
    key = f"{item.card_id}:{item.direction}"
    if session.mode == "learn":
        learn_algo.on_reveal(session, key)
    await db.commit()
    entry = await svc._entry_for_item(session, item)
    return {
        "ok": True,
        "correct_text": entry.answer_text if entry else "",
        "explanation": entry.explanation if entry else "",
        "example": entry.example if entry else "",
        "answer_context": entry.answer_context if entry else "",
    }


@router.put("/study-sessions/{session_id}/items/{item_id}/draft")
async def put_draft(
    session_id: str,
    item_id: str,
    payload: DraftIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    svc = StudyService(db, user)
    session = await svc.get_session(session_id)
    item = await svc.get_item(session, item_id)
    await svc.require_active(session)
    if item.draft_version != payload.draft_version:
        raise ApiError(
            409, "DRAFT_VERSION_CONFLICT", "Черновик изменён в другой вкладке.",
            {"current_draft_version": item.draft_version},
        )
    item.draft_answer = payload.draft
    item.draft_version += 1
    await db.commit()
    return {"ok": True, "draft_version": item.draft_version}


@router.post("/study-sessions/{session_id}/complete")
async def complete_session(
    session_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    from app.services.results_service import finalize_session

    svc = StudyService(db, user)
    session = await svc.get_session(session_id)
    if session.status == "completed":
        return await get_result_endpoint(session_id, db=db, user=user)  # идемпотентность
    result = await finalize_session(db, user, session)
    return result


@router.post("/study-sessions/{session_id}/abandon")
async def abandon_session(
    session_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    svc = StudyService(db, user)
    session = await svc.get_session(session_id)
    if session.status in ("active", "paused"):
        session.status = "abandoned"
        session.completed_at = utcnow()
        await db.commit()
    return {"ok": True}


@router.get("/study-sessions/{session_id}/result")
async def get_result_endpoint(
    session_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    from app.services.results_service import build_result

    svc = StudyService(db, user)
    session = await svc.get_session(session_id)
    return await build_result(db, session)




class CorrectionIn(BaseModel):
    final_correct: bool


@router.post("/study-sessions/{session_id}/answers/{answer_id}/correction")
async def correct_answer(
    session_id: str,
    answer_id: str,
    payload: CorrectionIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """«Засчитать мой ответ»: личная коррекция результата после автоматической ошибки.

    Исходная машинная оценка сохраняется (machine_correct), итоговая
    (final_correct) меняется; повторная коррекция не создаёт новую попытку.
    """
    svc = StudyService(db, user)
    session = await svc.get_session(session_id)
    answer = (
        await db.execute(
            select(StudyAnswer).where(
                StudyAnswer.id == answer_id,
                StudyAnswer.session_id == session.id,
                StudyAnswer.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if answer is None:
        raise ApiError(404, "NOT_FOUND", "Ответ не найден.")
    existing_correction = (
        await db.execute(
            select(StudyAnswer).where(StudyAnswer.correction_of_id == answer.id)
        )
    ).scalar_one_or_none()
    if existing_correction is not None:
        raise ApiError(409, "ALREADY_CORRECTED", "Коррекция уже применена.")
    if payload.final_correct == answer.final_correct:
        return {"ok": True, "final_correct": answer.final_correct, "unchanged": True}
    db.add(
        StudyAnswer(
            session_id=session.id,
            item_id=answer.item_id,
            user_id=user.id,
            client_event_id=f"corr:{answer.client_event_id}",
            # Коррекция — не новая попытка: отдельный диапазон номеров, чтобы
            # не нарушать уникальность (session_id, item_id, attempt_no).
            attempt_no=answer.attempt_no + 10000,
            raw_answer=None,
            machine_correct=answer.machine_correct,
            final_correct=payload.final_correct,
            assisted=answer.assisted,
            answer_type="manual_correction",
            correction_of_id=answer.id,
            fingerprint=f"corr:{answer.id}",
        )
    )
    answer.final_correct = payload.final_correct
    session.last_activity_at = utcnow()
    # Если тест уже завершён — пересчитать adjusted_score, не трогая исходный счёт.
    attempt = (
        await db.execute(select(TestAttempt).where(TestAttempt.session_id == session.id))
    ).scalar_one_or_none()
    adjusted = None
    if attempt is not None:
        answers = (
            await db.execute(
                select(StudyAnswer).where(
                    StudyAnswer.session_id == session.id,
                    StudyAnswer.answer_type != "manual_correction",
                )
            )
        ).scalars().all()
        final_by_item = {}
        for a in answers:
            final_by_item[a.item_id] = a.final_correct
        items = (
            await db.execute(select(StudySessionItem).where(StudySessionItem.session_id == session.id))
        ).scalars().all()
        score = 0
        max_score = 0
        for it in items:
            if it.task_type == "test_match":
                key = json.loads(it.answer_key_json or "{}")
                max_score += len(key.get("pairs", []))
                a = final_by_item.get(it.id)
                if a is True:
                    score += len(key.get("pairs", []))
            else:
                max_score += 1
                if final_by_item.get(it.id) is True:
                    score += 1
        adjusted = score
        attempt.adjusted_score = adjusted
    await db.commit()
    return {"ok": True, "final_correct": payload.final_correct, "adjusted_score": adjusted}


# ---------- Learn: выдача заданий ----------


@router.get("/study-sessions/{session_id}/next")
async def next_task(
    session_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    svc = StudyService(db, user)
    session = await svc.get_session(session_id)
    await svc.require_active(session)
    if session.mode != "learn":
        raise ApiError(422, "VALIDATION_ERROR", "Эндпоинт только для режима «Обучение».")
    pool = [deserialize_entry(d) for d in json.loads(session.pool_json)]
    pool_by_key = {f"{e.card_id}:{e.direction}": e for e in pool}
    key, status = learn_algo.next_task(session, pool_by_key, pool)
    if key is None:
        await db.commit()
        return {"round_complete": True, "status": status, "summary": learn_algo.round_summary(session)}
    entry = pool_by_key[key]
    task_type = status
    snapshot = item_snapshot_by_entry(entry)
    choices = None
    if task_type == "recognition":
        built = qgen.build_choices(entry, pool, qgen.seeded_rng(session.seed + session.current_index * 7919))
        if built is None:
            task_type = "written" if entry.written_check else "self_assess"
        else:
            choices, _ = built
    item = StudySessionItem(
        session_id=session.id, item_uid=new_uuid(), position=session.current_index,
        card_id=entry.card_id, direction=entry.direction, content_version=entry.content_version,
        task_type=task_type,
        snapshot_json=json.dumps(snapshot, ensure_ascii=False),
        choices_json=json.dumps(choices, ensure_ascii=False) if choices else None,
        answer_key_json=json.dumps(
            {"accepted": entry.accepted, "correct_text": entry.answer_text,
             "explanation": entry.explanation, "example": entry.example,
             "answer_context": entry.answer_context},
            ensure_ascii=False,
        ),
    )
    db.add(item)
    session.current_index += 1
    session.last_activity_at = utcnow()
    await db.commit()
    await db.refresh(item)
    ls = learn_algo._lstate(session)
    batch_info = {
        "batch_index": ls.get("batch_index", 1),
        "total_batches": len(ls.get("batches", [])),
        "queue_remaining": len(ls.get("queue", [])),
        "mastered_count": len(ls.get("mastered", [])),
    }
    return {"round_complete": False, "task": task_dto(item, session), "batch_info": batch_info}


def item_snapshot_by_entry(entry) -> dict:
    return {
        "question_text": entry.question_text,
        "question_context": entry.question_context,
        "hint": entry.hint,
        "explanation": entry.explanation,
        "example": entry.example,
        "language": entry.language,
        "media_question": entry.media_question or [],
        "media_answer": entry.media_answer or [],
    }


@router.post("/study-sessions/{session_id}/learn/repeat-failed")
async def learn_repeat_failed(
    session_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    svc = StudyService(db, user)
    session = await svc.get_session(session_id)
    await svc.require_active(session)
    result = learn_algo.start_repeat_failed_round(session)
    await db.commit()
    return {"ok": True, **result}


# ---------- Match ----------


@router.post("/study-sessions/{session_id}/match-moves")
async def match_moves(
    session_id: str,
    payload: MatchMoveIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.services.results_service import finalize_match

    svc = StudyService(db, user)
    session = await svc.get_session(session_id)
    await svc.require_active(session)
    if session.mode != "match":
        raise ApiError(422, "VALIDATION_ERROR", "Ходы доступны только в режиме «Подбор пар».")
    state = json.loads(session.state_json).get("match", {"matched": [], "mistakes": 0})
    if payload.first_item_id and payload.second_item_id:
        valid_ids = set(
            (
                await db.execute(
                    select(StudySessionItem.id).where(
                        StudySessionItem.session_id == session.id,
                        StudySessionItem.task_type == "match_pair",
                    )
                )
            ).scalars()
        )
        if payload.first_item_id not in valid_ids or payload.second_item_id not in valid_ids:
            raise ApiError(422, "VALIDATION_ERROR", "Плитка не принадлежит этой доске.")
        if payload.first_item_id == payload.second_item_id:
            if payload.first_item_id in state["matched"]:
                raise ApiError(409, "ALREADY_MATCHED", "Эта пара уже найдена.")
            state["matched"].append(payload.first_item_id)
            feedback = {"correct": True, "matched_count": len(state["matched"]),
                        "board_size": state.get("board_size", 0)}
        else:
            state["mistakes"] += 1
            feedback = {"correct": False, "mistakes": state["mistakes"], "penalty_ms": 3000}
        session.state_json = json.dumps({**json.loads(session.state_json), "match": state}, ensure_ascii=False)
        await db.commit()
        if len(state["matched"]) >= state.get("board_size", 0):
            await finalize_match(db, user, session, state)
            feedback["complete"] = True
            feedback["result"] = await get_result_endpoint(session_id, db=db, user=user)
        return feedback
    raise ApiError(422, "VALIDATION_ERROR", "Нужны две плитки.")


# ---------- DTO ----------


def task_dto(item: StudySessionItem, session: StudySession) -> dict:
    snap = item_snapshot(item)
    dto = {
        "item_id": item.id,
        "task_type": item.task_type,
        "direction": item.direction,
        "card_id": item.card_id,
        "content_version": item.content_version,
        "position": item.position,
        "status": item.status,
        "draft_version": item.draft_version,
        "question_text": snap.get("question_text"),
        "question_context": snap.get("question_context"),
        "hint": snap.get("hint"),
        "language": snap.get("language"),
        "media_question": snap.get("media_question", []),
        "media_answer": snap.get("media_answer", []),
        "choices": json.loads(item.choices_json) if item.choices_json else None,
    }
    if item.task_type == "spell" or session.mode == "spell":
        # Текст произносится браузерным TTS; скрыть его от пользователя невозможно.
        key = json.loads(item.answer_key_json) if item.answer_key_json else {}
        dto["tts_text"] = key.get("correct_text", "")
    if item.task_type == "match_pair":
        dto["match_right_text"] = snap.get("match_right_text", "")
    if item.task_type == "test_tf":
        dto["statement"] = snap.get("statement")
    if item.task_type == "test_match":
        dto["match_lefts"] = snap.get("match_lefts", [])
        dto["match_rights"] = snap.get("match_rights", [])
    # Ключ ответа не попадает в DTO до завершения теста.
    return dto


async def session_dto(db: AsyncSession, session: StudySession, include_items: bool) -> dict:
    items = (
        await db.execute(
            select(StudySessionItem)
            .where(StudySessionItem.session_id == session.id)
            .order_by(StudySessionItem.position)
        )
    ).scalars().all()
    dto = {
        "id": session.id,
        "mode": session.mode,
        "status": session.status,
        "settings": json.loads(session.settings_json),
        "seed": session.seed,
        "current_index": session.current_index,
        "active_ms": session.active_ms,
        "deadline_at": session.deadline_at,
        "started_at": session.started_at,
        "completed_at": session.completed_at,
        "item_count": len(json.loads(session.pool_json)),
    }
    if include_items and session.mode != "learn":
        dto["tasks"] = [task_dto(i, session) for i in items]
    return dto
