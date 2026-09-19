"""Завершение занятий и результаты. Оценки считает сервер."""
from __future__ import annotations

import json
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utcnow
from app.models import (
    ActivityEvent, MatchRecord, SetModel, StudyAnswer, StudySession, StudySessionItem,
    TestAttempt, User,
)
from app.services.local_dates import local_date_for


async def _record_activity(db: AsyncSession, user: User, event_type: str, session: StudySession, extra: dict | None = None, dedupe_key: str | None = None) -> None:
    db.add(
        ActivityEvent(
            user_id=user.id,
            event_type=event_type,
            local_date=local_date_for(user.timezone),
            set_id=None,
            dedupe_key=dedupe_key,
            meta_json=json.dumps({"mode": session.mode, "session_id": session.id, **(extra or {})}, ensure_ascii=False),
        )
    )


async def finalize_session(db: AsyncSession, user: User, session: StudySession) -> dict:
    if session.status == "completed":
        return await build_result(db, session)
    session.status = "completed"
    session.completed_at = utcnow()
    session.last_activity_at = utcnow()
    if session.mode == "test":
        await _finalize_test(db, user, session)
    await _record_activity(db, user, "session_completed", session, {"active_ms": session.active_ms})
    if session.active_ms >= 60000:
        minutes = session.active_ms // 60000
        await _record_activity(
            db, user, "study_minutes", session, {"minutes": minutes},
            dedupe_key=f"minutes:{session.id}",
        )
    await db.commit()
    return await build_result(db, session)


async def _finalize_test(db: AsyncSession, user: User, session: StudySession) -> None:
    items = (
        await db.execute(
            select(StudySessionItem)
            .where(StudySessionItem.session_id == session.id)
            .order_by(StudySessionItem.position)
        )
    ).scalars().all()
    answers = {
        a.item_id: a
        for a in (
            await db.execute(select(StudyAnswer).where(StudyAnswer.session_id == session.id))
        ).scalars().all()
    }
    score = 0
    max_score = 0
    detail = []
    for item in items:
        key = json.loads(item.answer_key_json or "{}")
        a = answers.get(item.id)
        if item.task_type == "test_match":
            pairs = key.get("pairs", [])
            mapping = {}
            if a and a.raw_answer:
                try:
                    mapping = json.loads(a.raw_answer)
                except Exception:
                    mapping = {}
            pair_results = [{"left": p["left"], "correct": mapping.get(p["left"]) == p["right"]} for p in pairs]
            earned = sum(1 for p in pair_results if p["correct"])
            max_score += len(pairs)
            score += earned
            detail.append({
                "item_id": item.id, "task_type": item.task_type,
                "question": "", "match_lefts": key.get("lefts", []), "match_rights": key.get("rights", []),
                "user_answer": mapping, "correct_pairs": pairs,
                "pair_results": pair_results, "earned": earned, "max": len(pairs),
                "skipped": item.skipped or a is None,
            })
            continue
        max_score += 1
        correct_text = key.get("correct_text")
        user_answer = (a.raw_answer if a and a.raw_answer else (item.draft_answer if item.draft_answer else None)) or ""
        if item.task_type == "test_tf":
            correct_display = key.get("is_true")
            user_display = a.raw_answer if a else None
            ok = bool(a and a.machine_correct)
        else:
            correct_display = correct_text
            user_display = user_answer
            ok = bool(a and a.final_correct)
        earned = 1 if ok else 0
        score += earned
        detail.append({
            "item_id": item.id, "task_type": item.task_type,
            "question": json.loads(item.snapshot_json or "{}").get("question_text", ""),
            "user_answer": user_display, "correct_answer": correct_display,
            "explanation": key.get("explanation", ""), "earned": earned, "max": 1,
            "skipped": item.skipped or a is None,
        })
    attempt = TestAttempt(
        user_id=user.id, session_id=session.id, score=score, max_score=max_score,
        detail_json=json.dumps(detail, ensure_ascii=False), finished_at=utcnow(),
    )
    db.add(attempt)
    session.result_json = json.dumps({"score": score, "max_score": max_score}, ensure_ascii=False)
    await _record_activity(db, user, "test_finished", session, {"score": score, "max_score": max_score})


async def finalize_match(db: AsyncSession, user: User, session: StudySession, match_state: dict) -> None:
    elapsed_ms = int((utcnow() - session.started_at).total_seconds() * 1000)
    mistakes = match_state.get("mistakes", 0)
    penalty_ms = mistakes * 3000
    final_ms = elapsed_ms + penalty_ms
    items = (
        await db.execute(
            select(StudySessionItem).where(StudySessionItem.session_id == session.id).order_by(StudySessionItem.position)
        )
    ).scalars().all()
    fingerprint_parts = "|".join(f"{i.card_id}:{i.content_version}:{i.direction}" for i in sorted(items, key=lambda x: x.id))
    import hashlib

    fingerprint = hashlib.sha256(fingerprint_parts.encode()).hexdigest()
    rec = MatchRecord(
        user_id=user.id, source_fingerprint=fingerprint,
        direction=items[0].direction if items else "front_to_back",
        board_size=len(items), penalty_rule="fixed_3000",
        elapsed_ms=elapsed_ms, mistakes=mistakes, penalty_ms=penalty_ms, final_ms=final_ms,
    )
    db.add(rec)
    session.status = "completed"
    session.completed_at = utcnow()
    session.result_json = json.dumps(
        {"elapsed_ms": elapsed_ms, "mistakes": mistakes, "penalty_ms": penalty_ms,
         "final_ms": final_ms, "board_size": len(items), "record_id": rec.id},
        ensure_ascii=False,
    )
    await _record_activity(db, user, "session_completed", session, {"mode": "match", "final_ms": final_ms})
    await db.commit()


async def build_result(db: AsyncSession, session: StudySession) -> dict:
    items = (
        await db.execute(
            select(StudySessionItem)
            .where(StudySessionItem.session_id == session.id)
            .order_by(StudySessionItem.position)
        )
    ).scalars().all()
    answers = {
        a.item_id: a
        for a in (
            await db.execute(
                select(StudyAnswer).where(
                    StudyAnswer.session_id == session.id, StudyAnswer.answer_type != "manual_correction"
                )
            )
        ).scalars().all()
    }
    source_ids = json.loads(session.sources_json or "[]")
    set_id = source_ids[0] if source_ids else None
    set_title = None
    if set_id:
        set_title = (await db.execute(select(SetModel.title).where(SetModel.id == set_id))).scalar_one_or_none()

    base = {
        "session_id": session.id,
        "mode": session.mode,
        "status": session.status,
        "active_ms": session.active_ms,
        "started_at": session.started_at,
        "completed_at": session.completed_at,
        "item_count": len(items),
        "set_id": set_id,
        "set_title": set_title,
        "set_ids": source_ids,
    }
    if session.mode == "test":
        attempt = (
            await db.execute(select(TestAttempt).where(TestAttempt.session_id == session.id))
        ).scalar_one_or_none()
        if attempt:
            detail = json.loads(attempt.detail_json)
            base.update(
                {
                    "score": attempt.score,
                    "max_score": attempt.max_score,
                    "percent": round(attempt.score * 100 / attempt.max_score) if attempt.max_score else None,
                    "adjusted_score": attempt.adjusted_score,
                    "detail": detail,
                }
            )
            base["history"] = await test_history(db, session.user_id)
        else:
            base["note"] = "not_finalized"
        return base
    if session.mode == "match":
        if session.result_json:
            r = json.loads(session.result_json)
            best = (
                await db.execute(
                    select(func.min(MatchRecord.final_ms)).where(
                        MatchRecord.user_id == session.user_id,
                        MatchRecord.source_fingerprint == (
                            (await db.execute(select(MatchRecord).where(MatchRecord.id == r.get("record_id")))).scalar_one_or_none().source_fingerprint
                            if r.get("record_id") else ""
                        ),
                    )
                )
            ).scalar_one_or_none()
            r["best_ms"] = best
            base.update(r)
        return base
    # cards / learn / write / spell
    per_item = []
    known = unknown = assisted_count = 0
    correct = incorrect = 0
    for item in items:
        a = answers.get(item.id)
        snap = json.loads(item.snapshot_json or "{}")
        row = {
            "item_id": item.id,
            "task_type": item.task_type,
            "question": snap.get("question_text", ""),
            "status": item.status,
            "skipped": item.skipped,
        }
        if a is not None:
            key = json.loads(item.answer_key_json or "{}") if item.answer_key_json else {}
            row.update(
                {
                    "user_answer": a.raw_answer,
                    "correct": a.final_correct,
                    "assisted": a.assisted,
                    "correct_text": key.get("correct_text", ""),
                    "explanation": key.get("explanation", ""),
                    "answer_type": a.answer_type,
                }
            )
            if a.assisted:
                assisted_count += 1
            if session.mode in ("write", "spell"):
                if a.final_correct:
                    correct += 1
                else:
                    incorrect += 1
            if session.mode == "cards":
                if a.final_correct:
                    known += 1
                else:
                    unknown += 1
        per_item.append(row)
    base.update(
        {
            "items": per_item,
            "assisted_count": assisted_count,
        }
    )
    if session.mode == "cards":
        base.update({"known": known, "unknown": unknown})
    if session.mode in ("write", "spell"):
        base.update({"correct": correct, "incorrect": incorrect})
    if session.mode == "learn":
        ls = json.loads(session.state_json).get("learn", {})
        base.update(
            {
                "mastered": ls.get("mastered", []),
                "round_failed": ls.get("round_failed", []),
                "hints_used": ls.get("hints_used", 0),
            }
        )
    return base


async def test_history(db: AsyncSession, user_id: str) -> list[dict]:
    rows = (
        await db.execute(
            select(TestAttempt)
            .where(TestAttempt.user_id == user_id)
            .order_by(TestAttempt.finished_at.desc())
            .limit(20)
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
