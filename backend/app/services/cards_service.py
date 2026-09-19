"""Сервис карточек: CRUD, батч-операции, порядок, массовые действия, смена сторон."""
from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.errors import ApiError
from app.db.base import utcnow
from app.models import (
    AcceptedAnswer, Card, CardMedia, SetModel, UserCardFlag,
)
from app.schemas.sets import CardIn, CardPatch
from app.services import search as search_index
from app.services.sets_service import _insert_card, bump_set_version


def _card_snapshot(card: Card) -> dict:
    """Публичный снимок карточки для занятий."""
    return {
        "front_text": card.front_text,
        "back_text": card.back_text,
        "front_context": card.front_context,
        "back_context": card.back_context,
        "front_hint": card.front_hint,
        "back_hint": card.back_hint,
        "front_explanation": card.front_explanation,
        "back_explanation": card.back_explanation,
        "front_example": card.front_example,
        "back_example": card.back_example,
        "front_language": card.front_language,
        "back_language": card.back_language,
        "written_check_front": card.written_check_front,
        "written_check_back": card.written_check_back,
        "enabled_front_to_back": card.enabled_front_to_back,
        "enabled_back_to_front": card.enabled_back_to_front,
    }


async def load_cards(db: AsyncSession, set_id: str, include_deleted: bool = False) -> list[Card]:
    q = (
        select(Card)
        .options(selectinload(Card.accepted_answers))
        .where(Card.set_id == set_id)
        .order_by(Card.position, Card.created_at, Card.id)
    )
    if not include_deleted:
        q = q.where(Card.deleted_at.is_(None))
    return list((await db.execute(q)).scalars().all())


async def list_cards_dto(
    db: AsyncSession, user_id: str, set_id: str, limit: int, offset: int
) -> tuple[list[Card], int]:
    total = (
        await db.execute(
            select(func.count()).select_from(Card).where(Card.set_id == set_id, Card.deleted_at.is_(None))
        )
    ).scalar_one()
    cards = (
        await db.execute(
            select(Card)
            .options(selectinload(Card.accepted_answers))
            .where(Card.set_id == set_id, Card.deleted_at.is_(None))
            .order_by(Card.position)
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()
    return list(cards), total


async def get_card(db: AsyncSession, card_id: str) -> Card:
    card = (
        await db.execute(
            select(Card)
            .options(selectinload(Card.accepted_answers))
            .where(Card.id == card_id, Card.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if card is None:
        raise ApiError(404, "NOT_FOUND", "Карточка не найдена.")
    return card


async def get_deleted_card(db: AsyncSession, card_id: str) -> Card:
    card = (
        await db.execute(
            select(Card)
            .options(selectinload(Card.accepted_answers))
            .where(Card.id == card_id, Card.deleted_at.is_not(None))
        )
    ).scalar_one_or_none()
    if card is None:
        raise ApiError(404, "NOT_FOUND", "Удалённая карточка не найдена.")
    return card


async def _normalize_positions(db: AsyncSession, set_id: str) -> None:
    cards = await load_cards(db, set_id)
    for position, card in enumerate(cards):
        card.position = position
    await db.flush()


PATCHABLE_FIELDS = (
    "front_text", "back_text", "front_context", "back_context", "front_hint",
    "back_hint", "front_explanation", "back_explanation", "front_example",
    "back_example", "front_language", "back_language", "enabled_front_to_back",
    "enabled_back_to_front", "written_check_front", "written_check_back",
)


async def apply_card_patch(db: AsyncSession, card: Card, payload: CardPatch) -> None:
    """Частичный патч: применяются только переданные поля (model_fields_set),
    иначе пустые дефолты стёрли бы текст существующей карточки."""
    provided = payload.model_fields_set
    for field in PATCHABLE_FIELDS:
        if field in provided:
            setattr(card, field, getattr(payload, field))
    card.content_version += 1
    card.updated_at = utcnow()
    await db.flush()
    if "accepted_front" in provided or "accepted_back" in provided:
        await _replace_accepted(db, card,
                               payload.accepted_front if "accepted_front" in provided else None,
                               payload.accepted_back if "accepted_back" in provided else None)
    await search_index.index_card(db, card.set_id, card)
    await db.flush()


async def _replace_accepted(
    db: AsyncSession, card: Card, front: list[str] | None, back: list[str] | None
) -> None:
    if front is not None:
        await db.execute(AcceptedAnswer.__table__.delete().where(AcceptedAnswer.card_id == card.id, AcceptedAnswer.side == "front"))
    if back is not None:
        await db.execute(AcceptedAnswer.__table__.delete().where(AcceptedAnswer.card_id == card.id, AcceptedAnswer.side == "back"))
    for side_key, answers in (("front", front), ("back", back)):
        if answers is None:
            continue
        for i, answer in enumerate(answers):
            clean = answer.strip()[:10000]
            if not clean:
                continue
            db.add(AcceptedAnswer(card_id=card.id, side=side_key, answer=clean, position=i))
    await db.flush()


async def create_card(db: AsyncSession, st: SetModel, payload: CardIn, at_position: int | None = None) -> Card:
    await _normalize_positions(db, st.id)
    count = (
        await db.execute(
            select(func.count()).select_from(Card).where(Card.set_id == st.id, Card.deleted_at.is_(None))
        )
    ).scalar_one()
    if count + 1 > settings.max_cards_per_set:
        raise ApiError(413, "TOO_MANY_CARDS", f"Максимум карточек в наборе: {settings.max_cards_per_set}.")
    position = count if at_position is None else max(0, min(at_position, count))
    if position < count:
        # Сдвигаем последующие позиции, не трогая ID.
        await db.execute(
            update(Card)
            .where(Card.set_id == st.id, Card.position >= position, Card.deleted_at.is_(None))
            .values(position=Card.position + 1)
        )
    card = await _insert_card(db, st.id, position, payload)
    await db.flush()
    return card


async def delete_card(db: AsyncSession, card: Card) -> None:
    card.deleted_at = utcnow()
    await db.flush()
    await search_index.remove_card(db, card.id)
    await _normalize_positions(db, card.set_id)


async def restore_card(db: AsyncSession, card: Card, at_position: int | None = None) -> Card:
    count = await card_count_of(db, card.set_id)
    position = count if at_position is None else max(0, min(at_position, count))
    await db.execute(
        update(Card)
        .where(Card.set_id == card.set_id, Card.position >= position, Card.deleted_at.is_(None))
        .values(position=Card.position + 1)
    )
    card.deleted_at = None
    card.position = position
    await db.flush()
    await search_index.index_card(db, card.set_id, card)
    return card


async def duplicate_card(db: AsyncSession, st: SetModel, source: Card, at_position: int | None = None) -> Card:
    accepted = list(source.accepted_answers)
    payload = CardIn(
        **_card_snapshot(source),
        accepted_front=[a.answer for a in accepted if a.side == "front"],
        accepted_back=[a.answer for a in accepted if a.side == "back"],
    )
    duplicate = await create_card(db, st, payload, at_position)
    media = (
        await db.execute(select(CardMedia).where(CardMedia.card_id == source.id))
    ).scalars().all()
    for item in media:
        db.add(CardMedia(card_id=duplicate.id, side=item.side, media_id=item.media_id, position=item.position))
    await db.flush()
    return duplicate


async def reorder_cards(db: AsyncSession, st: SetModel, ordered_ids: list[str]) -> None:
    """Транзакционная проверка принадлежности ID набору + перенумерация."""
    cards = await load_cards(db, st.id)
    current_ids = [c.id for c in cards]
    if sorted(current_ids) != sorted(ordered_ids) or len(ordered_ids) != len(current_ids):
        raise ApiError(422, "VALIDATION_ERROR", "Список порядка не совпадает с карточками набора.")
    pos_map = {cid: i for i, cid in enumerate(ordered_ids)}
    for card in cards:
        card.position = pos_map[card.id]
    await db.flush()


async def bulk_delete(db: AsyncSession, st: SetModel, card_ids: list[str]) -> int:
    cards = (
        await db.execute(
            select(Card).where(Card.set_id == st.id, Card.id.in_(card_ids), Card.deleted_at.is_(None))
        )
    ).scalars().all()
    for card in cards:
        card.deleted_at = utcnow()
        await search_index.remove_card(db, card.id)
    await db.flush()
    await _normalize_positions(db, st.id)
    return len(cards)


async def bulk_move(db: AsyncSession, source: SetModel, target: SetModel, card_ids: list[str]) -> int:
    """Перенос только между наборами одного владельца; card_id и история сохраняются."""
    if source.owner_id != target.owner_id:
        raise ApiError(403, "FORBIDDEN", "Перенос возможен только между своими наборами.")
    if source.id == target.id:
        raise ApiError(422, "VALIDATION_ERROR", "Наборы совпадают.")
    cards = (
        await db.execute(
            select(Card)
            .options(selectinload(Card.accepted_answers))
            .where(Card.set_id == source.id, Card.id.in_(card_ids), Card.deleted_at.is_(None))
        )
    ).scalars().all()
    if len(cards) != len(set(card_ids)):
        raise ApiError(404, "NOT_FOUND", "Некоторые карточки не найдены в исходном наборе.")
    target_count = await card_count_of(db, target.id)
    if target_count + len(cards) > settings.max_cards_per_set:
        raise ApiError(413, "TOO_MANY_CARDS", "Превышен лимит карточек целевого набора.")
    for i, card in enumerate(cards):
        card.set_id = target.id
        card.position = target_count + i
        card.content_version += 1
        await search_index.remove_card(db, card.id)
    await db.flush()
    for card in cards:
        await search_index.index_card(db, target.id, card)
    await _normalize_positions(db, source.id)
    await _normalize_positions(db, target.id)
    await db.flush()
    return len(cards)


async def card_count_of(db: AsyncSession, set_id: str) -> int:
    return (
        await db.execute(
            select(func.count()).select_from(Card).where(Card.set_id == set_id, Card.deleted_at.is_(None))
        )
    ).scalar_one()


def _swap_card_fields(card: CardModel) -> None:
    (
        card.front_text, card.back_text,
        card.front_context, card.back_context,
        card.front_hint, card.back_hint,
        card.front_explanation, card.back_explanation,
        card.front_example, card.back_example,
        card.front_language, card.back_language,
        card.enabled_front_to_back, card.enabled_back_to_front,
        card.written_check_front, card.written_check_back,
    ) = (
        card.back_text, card.front_text,
        card.back_context, card.front_context,
        card.back_hint, card.front_hint,
        card.back_explanation, card.front_explanation,
        card.back_example, card.front_example,
        card.back_language, card.front_language,
        card.enabled_back_to_front, card.enabled_front_to_back,
        card.written_check_back, card.written_check_front,
    )
    answers = list(card.accepted_answers)
    front = sorted([a for a in answers if a.side == "front"], key=lambda a: a.position)
    back = sorted([a for a in answers if a.side == "back"], key=lambda a: a.position)
    for a in front:
        a.side = "back_tmp"
    for a in back:
        a.side = "front"
    for a in front:
        a.side = "back"
    card.content_version += 1
    card.updated_at = utcnow()


async def swap_single_card_sides(db: AsyncSession, card: CardModel) -> None:
    _swap_card_fields(card)
    await db.flush()
    await search_index.index_card(db, card.set_id, card)
    from app.services import srs_service
    await srs_service.swap_directions(db, [card.id])


async def swap_sides(db: AsyncSession, st: SetModel) -> int:
    """Смысловая операция: контент сторон и состояния памяти обмениваются согласованно."""
    cards = await load_cards(db, st.id)
    for card in cards:
        _swap_card_fields(card)
        await db.flush()
        await search_index.index_card(db, st.id, card)
    await db.flush()
    # Состояния памяти: прежнее front_to_back становится back_to_front (по всем пользователям).
    from app.services import srs_service

    await srs_service.swap_directions(db, [c.id for c in cards])
    return len(cards)
