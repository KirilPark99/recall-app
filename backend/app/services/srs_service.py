"""SRS-сервис: enrollment, очередь, reviews (одна транзакция), undo, reset."""
from __future__ import annotations

import json
from datetime import timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.db.base import new_uuid, utcnow
from app.models import (
    ActivityEvent, Card, SetModel, SrsEnrollment, SrsReview, SrsSettings, SrsState, User,
)
from app.services import access as access_service
from app.services.local_dates import local_date_for
from app.srs import adapter as fsrs
from app.srs.adapter import SchedulerConfig

DIRECTIONS = ("front_to_back", "back_to_front")


async def get_srs_settings(db: AsyncSession, user_id: str) -> SrsSettings:
    row = (
        await db.execute(select(SrsSettings).where(SrsSettings.user_id == user_id))
    ).scalar_one_or_none()
    if row is None:
        row = SrsSettings(user_id=user_id)
        db.add(row)
        await db.flush()
    return row


def scheduler_config(settings_row: SrsSettings) -> SchedulerConfig:
    retention = min(max(settings_row.desired_retention, 0.80), 0.97)
    return SchedulerConfig(desired_retention=retention, enable_fuzzing=False)


async def enroll(
    db: AsyncSession, user: User, set_id: str, enabled: bool,
    forward_enabled: bool, reverse_enabled: bool,
) -> dict:
    """Включение повторения — явное действие, не побочный эффект создания набора."""
    await access_service.get_set_access(db, user, set_id)
    row = (
        await db.execute(
            select(SrsEnrollment).where(SrsEnrollment.user_id == user.id, SrsEnrollment.set_id == set_id)
        )
    ).scalar_one_or_none()
    if row is None:
        row = SrsEnrollment(
            user_id=user.id, set_id=set_id, enabled=enabled,
            forward_enabled=forward_enabled, reverse_enabled=reverse_enabled,
        )
        db.add(row)
    else:
        row.enabled = enabled
        row.forward_enabled = forward_enabled
        row.reverse_enabled = reverse_enabled
    await db.commit()
    return {
        "set_id": set_id, "enabled": row.enabled,
        "forward_enabled": row.forward_enabled, "reverse_enabled": row.reverse_enabled,
    }


async def overview(db: AsyncSession, user: User) -> dict:
    """Агрегаты очереди: сейчас к повторению, позже, новые, приостановленные."""
    settings_row = await get_srs_settings(db, user.id)
    now = utcnow()
    states = (
        await db.execute(
            select(SrsState)
            .join(Card, Card.id == SrsState.card_id)
            .join(SetModel, SetModel.id == Card.set_id)
            .where(
                SrsState.user_id == user.id,
                Card.deleted_at.is_(None),
                SetModel.deleted_at.is_(None),
                access_service.visible_sets_condition(user),
            )
        )
    ).scalars().all()
    due_now = later = suspended_count = learning_count = 0
    for s in states:
        if s.suspended:
            suspended_count += 1
            continue
        if s.due_at <= now:
            due_now += 1
        else:
            later += 1
        if s.state_name in ("learning", "relearning"):
            learning_count += 1
    new_count = await count_new_cards(db, user)
    return {
        "due_now": due_now,
        "later": later,
        "new": new_count,
        "new_limit": settings_row.new_per_day,
        "learning": learning_count,
        "suspended": suspended_count,
        "total_tracked": len(states),
        "desired_retention": settings_row.desired_retention,
    }


def learning_or_new(count, learning, relearning, review):
    return (learning or 0) + (relearning or 0)


async def count_new_cards(db: AsyncSession, user: User) -> int:
    enrolled = (
        await db.execute(
            select(SrsEnrollment)
            .join(SetModel, SetModel.id == SrsEnrollment.set_id)
            .where(
                SrsEnrollment.user_id == user.id,
                SrsEnrollment.enabled.is_(True),
                SetModel.deleted_at.is_(None),
                access_service.visible_sets_condition(user),
            )
        )
    ).scalars().all()
    if not enrolled:
        return 0
    total = 0
    for e in enrolled:
        cond = [Card.set_id == e.set_id, Card.deleted_at.is_(None)]
        dirs = []
        if e.forward_enabled:
            dirs.append("front_to_back")
        if e.reverse_enabled:
            dirs.append("back_to_front")
        for d in dirs:
            sub = select(SrsState.card_id).where(
                SrsState.user_id == user.id, SrsState.card_id == Card.id, SrsState.direction == d
            )
            count = (
                await db.execute(
                    select(func.count())
                    .select_from(Card)
                    .where(*cond, ~sub.exists())
                )
            ).scalar_one()
            total += count
    return total


async def queue(db: AsyncSession, user: User, limit: int | None = None) -> list[dict]:
    """Порядок: сначала просроченные/наступившие повторения, затем новые (лимит)."""
    settings_row = await get_srs_settings(db, user.id)
    cfg = scheduler_config(settings_row)
    now = utcnow()
    enrolled = (
        await db.execute(
            select(SrsEnrollment)
            .join(SetModel, SetModel.id == SrsEnrollment.set_id)
            .where(
                SrsEnrollment.user_id == user.id,
                SrsEnrollment.enabled.is_(True),
                SetModel.deleted_at.is_(None),
                access_service.visible_sets_condition(user),
            )
        )
    ).scalars().all()
    if not enrolled:
        return []
    set_ids = [e.set_id for e in enrolled]
    dir_map = {}
    for e in enrolled:
        dirs = []
        if e.forward_enabled:
            dirs.append("front_to_back")
        if e.reverse_enabled:
            dirs.append("back_to_front")
        dir_map[e.set_id] = dirs
    rows = (
        await db.execute(
            select(Card, SrsState)
            .join(SrsState, (SrsState.card_id == Card.id) & (SrsState.user_id == user.id))
            .where(
                Card.set_id.in_(set_ids),
                Card.deleted_at.is_(None),
                SrsState.suspended.is_(False),
                SrsState.direction.in_([d for ds in dir_map.values() for d in ds]),
            )
            .order_by(SrsState.due_at)
            .limit(500)
        )
    ).all()
    allowed_sets = {sid: ds for sid, ds in dir_map.items() if ds}
    out = []
    for card, state in rows:
        if state.direction not in dir_map.get(card.set_id, []):
            continue
        if card.set_id in allowed_sets:
            out.append({"card": card, "state": state})
    due_items = [x for x in out if x["state"].due_at <= now]
    later_items = [x for x in out if x["state"].due_at > now]
    result = [
        {
            "card_id": item["card"].id,
            "state_id": item["state"].id,
            "direction": item["state"].direction,
            "state_name": item["state"].state_name,
            "due_at": item["state"].due_at,
            "is_new": False,
            "suspended": item["state"].suspended,
        }
        for item in due_items
    ]
    # Новые единицы: в пределах дневного лимита, учёт при первом принятом review.
    used_today = await new_reviews_today(db, user)
    remaining = settings_row.new_per_day - used_today
    if remaining > 0:
        new_cards = await fetch_new_for_queue(db, user, dir_map, remaining)
        for card, direction in new_cards:
            result.append(
                {"card_id": card.id, "state_id": None, "direction": direction,
                 "state_name": "new", "due_at": now, "is_new": True, "suspended": False}
            )
    if limit:
        result = result[:limit]
    return result


async def new_reviews_today(db: AsyncSession, user: User) -> int:
    """Новые единицы считаются по локальной дате пользователя при первом принятом review."""
    today = local_date_for(user.timezone)
    res2 = (
        await db.execute(
            select(func.count()).select_from(ActivityEvent).where(
                ActivityEvent.user_id == user.id,
                ActivityEvent.event_type == "srs_new_review",
                ActivityEvent.local_date == today,
            )
        )
    ).scalar_one()
    return res2


async def fetch_new_for_queue(db: AsyncSession, user: User, dir_map: dict, limit: int) -> list:
    out = []
    for set_id, dirs in dir_map.items():
        for d in dirs:
            sub = select(SrsState.id).where(
                SrsState.user_id == user.id, SrsState.card_id == Card.id, SrsState.direction == d
            )
            rows = (
                await db.execute(
                    select(Card)
                    .where(Card.set_id == set_id, Card.deleted_at.is_(None), ~sub.exists())
                    .order_by(Card.position)
                    .limit(limit - len(out))
                )
            ).scalars().all()
            for c in rows:
                out.append((c, d))
            if len(out) >= limit:
                return out
    return out


async def submit_review(
    db: AsyncSession, user: User, card_id: str, direction: str, rating: str,
    expected_state_version: int | None, expected_content_version: int | None,
    client_event_id: str, study_session_id: str | None,
) -> dict:
    """Канонический приём review: одна транзакция — событие + состояние + журнал."""
    if direction not in DIRECTIONS:
        raise ApiError(422, "VALIDATION_ERROR", "Недопустимое направление.")
    if rating not in ("again", "hard", "good", "easy"):
        raise ApiError(422, "VALIDATION_ERROR", "Оценка: again, hard, good или easy.")
    # Идемпотентность по client_event_id.
    existing = (
        await db.execute(
            select(SrsReview).where(SrsReview.user_id == user.id, SrsReview.idempotency_key == client_event_id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return {
            "review_id": existing.id, "replayed": True,
            "due_at": existing.after_due_at, "state_name": json.loads(existing.after_payload)["card"]["state"],
        }

    card = (
        await db.execute(select(Card).where(Card.id == card_id, Card.deleted_at.is_(None)))
    ).scalar_one_or_none()
    if card is None:
        raise ApiError(404, "NOT_FOUND", "Карточка не найдена.")
    if expected_content_version is not None and card.content_version != expected_content_version:
        raise ApiError(409, "CARD_VERSION_CONFLICT", "Карточка изменилась; обновите вопрос.",
                       {"current_content_version": card.content_version})
    # Доступ к набору и включённое направление.
    from app.services.access import get_set_access

    access = await get_set_access(db, user, card.set_id)
    enrollment = (
        await db.execute(
            select(SrsEnrollment).where(SrsEnrollment.user_id == user.id, SrsEnrollment.set_id == card.set_id)
        )
    ).scalar_one_or_none()
    if enrollment is None or not enrollment.enabled:
        raise ApiError(409, "SRS_NOT_ENROLLED", "Набор не включён в повторение.")
    if direction == "front_to_back" and not enrollment.forward_enabled:
        raise ApiError(409, "DIRECTION_DISABLED", "Направление отключено в настройках повторения.")
    if direction == "back_to_front" and not enrollment.reverse_enabled:
        raise ApiError(409, "DIRECTION_DISABLED", "Направление отключено в настройках повторения.")
    if access.set.archived:
        raise ApiError(409, "SET_ARCHIVED", "Набор в архиве.")

    state = (
        await db.execute(
            select(SrsState).where(
                SrsState.user_id == user.id, SrsState.card_id == card_id, SrsState.direction == direction
            )
        )
    ).scalar_one_or_none()
    is_new_unit = state is None
    settings_row = await get_srs_settings(db, user.id)
    cfg = scheduler_config(settings_row)
    # Лимит новых единиц: две вкладки не должны обойти его (условие проверяется в транзакции).
    if is_new_unit:
        used = await new_reviews_today(db, user)
        if used >= settings_row.new_per_day:
            raise ApiError(409, "NEW_LIMIT_REACHED", "Дневной лимит новых карточек исчерпан.")
    if state is not None:
        if state.suspended:
            raise ApiError(409, "STATE_SUSPENDED", "Единица приостановлена.")
        if expected_state_version is not None and state.version != expected_state_version:
            raise ApiError(
                409, "SRS_VERSION_CONFLICT", "Состояние изменено в другой вкладке.",
                {"current_state_version": state.version},
            )
        if state.last_reviewed_content_version != card.content_version and state.last_review_at is not None:
            raise ApiError(409, "CARD_VERSION_CONFLICT", "Карточка изменилась после последнего повторения; обновите вопрос.")

    now = utcnow()
    payload = json.loads(state.scheduler_payload) if state is not None else fsrs.new_payload()
    before_due = state.due_at if state is not None else None
    before_version = state.version if state is not None else 0
    try:
        after_payload = fsrs.review(payload, rating, now, cfg)
    except Exception:
        raise ApiError(500, "SRS_ERROR", "Ошибка планировщика.")
    after_due = fsrs.due_at(after_payload)
    after_state_name = fsrs.state_name(after_payload)

    if state is None:
        state = SrsState(
            user_id=user.id, card_id=card_id, direction=direction,
            algorithm_name=fsrs.ALGORITHM_NAME, algorithm_version=fsrs.ALGORITHM_VERSION,
            scheduler_payload=json.dumps(after_payload, ensure_ascii=False),
            due_at=after_due, last_review_at=now, state_name=after_state_name,
            last_reviewed_content_version=card.content_version, version=1,
        )
        db.add(state)
        await db.flush()
        after_version = state.version
    else:
        # Conditional update по version: конкурентная вкладка получит конфликт.
        res = await db.execute(
            update(SrsState)
            .where(SrsState.id == state.id, SrsState.version == before_version)
            .values(
                scheduler_payload=json.dumps(after_payload, ensure_ascii=False),
                due_at=after_due, last_review_at=now, state_name=after_state_name,
                last_reviewed_content_version=card.content_version,
                version=before_version + 1, updated_at=now,
            )
        )
        if res.rowcount == 0:
            raise ApiError(409, "SRS_VERSION_CONFLICT", "Состояние изменено в другой вкладке.")
        after_version = before_version + 1
        await db.refresh(state)

    review = SrsReview(
        user_id=user.id, card_id=card_id, direction=direction, srs_state_id=state.id,
        rating={"again": 1, "hard": 2, "good": 3, "easy": 4}[rating],
        before_payload=json.dumps(payload, ensure_ascii=False),
        after_payload=json.dumps(after_payload, ensure_ascii=False),
        before_due_at=before_due, after_due_at=after_due,
        before_state_version=before_version, after_state_version=after_version,
        card_content_version=card.content_version,
        study_session_id=study_session_id,
        reviewed_at=now,
        idempotency_key=client_event_id,
        learning_epoch=state.learning_epoch,
    )
    db.add(review)
    await db.flush()
    today = local_date_for(user.timezone)
    db.add(
        ActivityEvent(
            user_id=user.id, event_type="srs_review", local_date=today,
            set_id=card.set_id, card_id=card_id,
            dedupe_key=None,
            meta_json=json.dumps({"rating": rating, "direction": direction, "review_id": review.id}, ensure_ascii=False),
        )
    )
    if is_new_unit:
        db.add(
            ActivityEvent(
                user_id=user.id, event_type="srs_new_review", local_date=today,
                set_id=card.set_id, card_id=card_id, dedupe_key=review.id,
                meta_json=json.dumps({"review_id": review.id}, ensure_ascii=False),
            )
        )
    await db.commit()
    return {
        "review_id": review.id, "replayed": False,
        "due_at": after_due, "state_name": after_state_name,
        "interval": fsrs.preview_intervals(after_payload, cfg).get("good"),
    }


async def undo_last_review(db: AsyncSession, user: User, review_id: str) -> dict:
    """Только последний review единицы: восстановление payload, version растёт."""
    review = (
        await db.execute(
            select(SrsReview).where(SrsReview.id == review_id, SrsReview.user_id == user.id)
        )
    ).scalar_one_or_none()
    if review is None:
        raise ApiError(404, "NOT_FOUND", "Оценка не найдена.")
    if review.undone_at is not None or review.is_undo_event:
        raise ApiError(409, "ALREADY_UNDONE", "Эта оценка уже отменена.")
    newer = (
        await db.execute(
            select(SrsReview.id)
            .where(
                SrsReview.user_id == user.id,
                SrsReview.card_id == review.card_id,
                SrsReview.direction == review.direction,
                SrsReview.reviewed_at > review.reviewed_at,
                SrsReview.is_undo_event.is_(False),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if newer is not None:
        raise ApiError(409, "NOT_LAST_REVIEW", "Отменить можно только последнюю оценку единицы.")
    state = (
        await db.execute(select(SrsState).where(SrsState.id == review.srs_state_id))
    ).scalar_one_or_none()
    if state is None:
        raise ApiError(404, "NOT_FOUND", "Состояние не найдено.")
    now = utcnow()
    before_payload = json.loads(review.before_payload)
    state.scheduler_payload = review.before_payload
    state.due_at = review.before_due_at or now
    last_review_iso = before_payload["card"].get("last_review")
    if last_review_iso:
        from datetime import datetime

        state.last_review_at = datetime.fromisoformat(last_review_iso).replace(tzinfo=None)
    else:
        state.last_review_at = None
    state.state_name = fsrs.state_name(before_payload)
    state.version += 1
    state.updated_at = now
    review.undone_at = now
    db.add(
        SrsReview(
            user_id=user.id, card_id=review.card_id, direction=review.direction,
            srs_state_id=state.id, rating=review.rating,
            before_payload=review.after_payload, after_payload=review.before_payload,
            before_due_at=review.after_due_at, after_due_at=review.before_due_at or now,
            before_state_version=review.after_state_version, after_state_version=state.version,
            card_content_version=review.card_content_version,
            reviewed_at=now, is_undo_event=True,
            idempotency_key=f"undo:{review.idempotency_key}",
            learning_epoch=state.learning_epoch,
        )
    )
    await db.commit()
    return {"ok": True, "due_at": state.due_at}


async def reset_progress(db: AsyncSession, user: User, card_ids: list[str], directions: list[str]) -> int:
    """Сброс создаёт новую учебную эпоху; старая история остаётся для статистики."""
    affected = 0
    for direction in directions or list(DIRECTIONS):
        states = (
            await db.execute(
                select(SrsState).where(
                    SrsState.user_id == user.id,
                    SrsState.card_id.in_(card_ids),
                    SrsState.direction == direction,
                )
            )
        ).scalars().all()
        for state in states:
            state.learning_epoch += 1
            state.version += 1
            payload = fsrs.new_payload()
            state.scheduler_payload = json.dumps(payload, ensure_ascii=False)
            state.due_at = utcnow()
            state.last_review_at = None
            state.state_name = "new"
            state.updated_at = utcnow()
            affected += 1
    await db.commit()
    return affected


async def last_review_for(db: AsyncSession, user: User, card_id: str, direction: str) -> SrsReview | None:
    return (
        await db.execute(
            select(SrsReview)
            .where(
                SrsReview.user_id == user.id,
                SrsReview.card_id == card_id,
                SrsReview.direction == direction,
                SrsReview.is_undo_event.is_(False),
                SrsReview.undone_at.is_(None),
            )
            .order_by(SrsReview.reviewed_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def on_set_deleted(db: AsyncSession, user_id: str, set_id: str) -> None:
    await db.execute(
        delete(SrsEnrollment).where(SrsEnrollment.set_id == set_id)
    )


async def swap_directions(db: AsyncSession, card_ids: list[str]) -> None:
    """Меняет направление front_to_back <-> back_to_front для карточек."""
    if not card_ids:
        return
    # Смена в SrsState через временное значение (во избежание нарушения UniqueConstraint)
    await db.execute(
        update(SrsState)
        .where(SrsState.card_id.in_(card_ids), SrsState.direction == "front_to_back")
        .values(direction="tmp_swap")
    )
    await db.execute(
        update(SrsState)
        .where(SrsState.card_id.in_(card_ids), SrsState.direction == "back_to_front")
        .values(direction="front_to_back")
    )
    await db.execute(
        update(SrsState)
        .where(SrsState.card_id.in_(card_ids), SrsState.direction == "tmp_swap")
        .values(direction="back_to_front")
    )
    # Смена в SrsReview
    await db.execute(
        update(SrsReview)
        .where(SrsReview.card_id.in_(card_ids), SrsReview.direction == "front_to_back")
        .values(direction="tmp_swap")
    )
    await db.execute(
        update(SrsReview)
        .where(SrsReview.card_id.in_(card_ids), SrsReview.direction == "back_to_front")
        .values(direction="front_to_back")
    )
    await db.execute(
        update(SrsReview)
        .where(SrsReview.card_id.in_(card_ids), SrsReview.direction == "tmp_swap")
        .values(direction="back_to_front")
    )
    await db.flush()
