"""Поиск: FTS5 (unicode61) с синхронизацией в транзакции; fallback на LIKE."""
from __future__ import annotations

from sqlalchemy import func, or_, select, text as sqltext
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AcceptedAnswer, Card, SetModel, Tag, SetTag


async def _fts_available(db: AsyncSession) -> bool:
    """FTS доступен, если таблица search_fts реально существует (создана миграцией)."""
    res = await db.execute(
        sqltext("SELECT 1 FROM sqlite_master WHERE type='table' AND name='search_fts'")
    )
    return res.scalar() is not None


async def index_card(db: AsyncSession, set_id: str, card: Card, extra_text: str = "") -> None:
    """Переиндексация одной карточки (вызывается в той же транзакции изменения)."""
    if not await _fts_available(db):
        return
    body = " ".join(
        filter(None, [card.front_text, card.back_text, card.front_context, card.back_context])
    )
    await db.execute(
        sqltext("DELETE FROM search_fts WHERE card_id = :cid"), {"cid": card.id}
    )
    if body:
        await db.execute(
            sqltext(
                "INSERT INTO search_fts(text, set_id, card_id) VALUES (:t, :sid, :cid)"
            ),
            {"t": body, "sid": set_id, "cid": card.id},
        )


async def index_set_meta(db: AsyncSession, set_row: SetModel, tag_names: list[str]) -> None:
    """Документ набора: название, описание, теги."""
    if not await _fts_available(db):
        return
    await db.execute(
        sqltext("DELETE FROM search_fts WHERE card_id = '' AND set_id = :sid"), {"sid": set_row.id}
    )
    body = " ".join(filter(None, [set_row.title, set_row.description, " ".join(tag_names)]))
    if body:
        await db.execute(
            sqltext(
                "INSERT INTO search_fts(text, set_id, card_id) VALUES (:t, :sid, '')"
            ),
            {"t": body, "sid": set_row.id},
        )


async def remove_card(db: AsyncSession, card_id: str) -> None:
    if not await _fts_available(db):
        return
    await db.execute(sqltext("DELETE FROM search_fts WHERE card_id = :cid"), {"cid": card_id})


async def remove_set(db: AsyncSession, set_id: str) -> None:
    if not await _fts_available(db):
        return
    await db.execute(
        sqltext("DELETE FROM search_fts WHERE set_id = :sid"), {"sid": set_id}
    )


def sanitize_fts_query(q: str) -> str:
    """Каждый терм — в кавычках (спецсимволы FTS безопасны), префиксный поиск."""
    terms = [t for t in q.replace('"', " ").split() if t]
    return " ".join(f'"{t}"*' for t in terms)


async def search_set_ids(
    db: AsyncSession, query: str, visible_condition
) -> list[str]:
    """Возвращает set_id через FTS5 либо переносимый LIKE fallback."""
    sanitized = sanitize_fts_query(query)
    if not sanitized:
        return []
    if await _fts_available(db):
        rows = await db.execute(
            sqltext(
                "SELECT DISTINCT set_id FROM search_fts WHERE search_fts MATCH :q LIMIT 1000"
            ),
            {"q": sanitized},
        )
        return [r[0] for r in rows.fetchall()]
    needle = f"%{query.strip().lower()}%"
    set_matches = select(SetModel.id).where(
        or_(func.lower(SetModel.title).like(needle), func.lower(SetModel.description).like(needle))
    )
    card_matches = select(Card.set_id).where(
        Card.deleted_at.is_(None),
        or_(
            func.lower(Card.front_text).like(needle),
            func.lower(Card.back_text).like(needle),
            func.lower(Card.front_context).like(needle),
            func.lower(Card.back_context).like(needle),
        ),
    )
    tag_matches = select(SetTag.set_id).join(Tag, Tag.id == SetTag.tag_id).where(
        func.lower(Tag.name).like(needle)
    )
    rows = await db.execute(set_matches.union(card_matches, tag_matches).limit(1000))
    return list(rows.scalars())
