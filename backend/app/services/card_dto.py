"""Сборка CardOut (медиа, допустимые ответы, звёздочка) без N+1."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Card, CardMedia, Media, UserCardFlag
from app.schemas.sets import CardOut, MediaOut


async def build_card_dtos(db: AsyncSession, user_id: str, cards: list[Card]) -> list[CardOut]:
    if not cards:
        return []
    card_ids = [c.id for c in cards]
    media_rows = (
        await db.execute(
            select(CardMedia, Media)
            .join(Media, Media.id == CardMedia.media_id)
            .where(CardMedia.card_id.in_(card_ids), Media.deleted_at.is_(None))
            .order_by(CardMedia.position)
        )
    ).all()
    media_by_card: dict[str, dict[str, list[MediaOut]]] = {}
    for cm, m in media_rows:
        media_by_card.setdefault(cm.card_id, {"front": [], "back": []})[cm.side].append(
            MediaOut(
                id=m.id,
                media_type=m.media_type,
                mime_type=m.mime_type,
                original_name=m.original_name,
                description=m.description,
                width=m.width,
                height=m.height,
                duration_ms=m.duration_ms,
            )
        )
    flags = {
        r[0]: r[1]
        for r in (
            await db.execute(
                select(UserCardFlag.card_id, UserCardFlag.is_starred).where(
                    UserCardFlag.user_id == user_id, UserCardFlag.card_id.in_(card_ids)
                )
            )
        ).all()
    }
    out = []
    for c in cards:
        acc_front = [a.answer for a in sorted((a for a in c.accepted_answers if a.side == "front"), key=lambda a: a.position)]
        acc_back = [a.answer for a in sorted((a for a in c.accepted_answers if a.side == "back"), key=lambda a: a.position)]
        media = media_by_card.get(c.id, {})
        out.append(
            CardOut(
                id=c.id,
                set_id=c.set_id,
                position=c.position,
                content_version=c.content_version,
                front_text=c.front_text,
                back_text=c.back_text,
                front_context=c.front_context,
                back_context=c.back_context,
                front_hint=c.front_hint,
                back_hint=c.back_hint,
                front_explanation=c.front_explanation,
                back_explanation=c.back_explanation,
                front_example=c.front_example,
                back_example=c.back_example,
                front_language=c.front_language,
                back_language=c.back_language,
                enabled_front_to_back=c.enabled_front_to_back,
                enabled_back_to_front=c.enabled_back_to_front,
                written_check_front=c.written_check_front,
                written_check_back=c.written_check_back,
                accepted_front=acc_front,
                accepted_back=acc_back,
                front_media=media.get("front", []),
                back_media=media.get("back", []),
                is_starred=flags.get(c.id, False),
                updated_at=c.updated_at,
            )
        )
    return out


async def load_set_cards(db: AsyncSession, set_id: str) -> list[Card]:
    return list(
        (
            await db.execute(
                select(Card)
                .options(selectinload(Card.accepted_answers))
                .where(Card.set_id == set_id, Card.deleted_at.is_(None))
                .order_by(Card.position)
            )
        ).scalars()
    )
