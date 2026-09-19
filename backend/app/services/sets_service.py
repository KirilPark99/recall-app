"""Сервис наборов: CRUD, копирование, архив, библиотека, избранное, каталог."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.errors import ApiError
from app.db.base import utcnow
from app.models import (
    Card, FolderSet, LibraryEntry, SetModel, SetTag, SrsEnrollment, Tag, User,
    UserCardFlag,
)
from app.schemas.sets import CardIn, SetCreate, SetPatch
from app.services import search as search_index
from app.services.access import hidden_error


async def bump_set_version(db: AsyncSession, set_id: str, expected: int | None = None) -> int:
    """Optimistic concurrency: инкремент content_version с проверкой ожидаемой версии."""
    st = (await db.execute(select(SetModel).where(SetModel.id == set_id))).scalar_one()
    if expected is not None and st.content_version != expected:
        raise ApiError(
            409,
            "SET_VERSION_CONFLICT",
            "Набор изменился в другой вкладке.",
            {"current_content_version": st.content_version},
        )
    st.content_version += 1
    st.updated_at = utcnow()
    await db.flush()
    return st.content_version


async def _get_or_create_tags(db: AsyncSession, owner_id: str, names: list[str]) -> list[Tag]:
    tags: list[Tag] = []
    seen: set[str] = set()
    for name in names:
        clean = name.strip()[:64]
        if not clean:
            continue
        norm = clean.lower()
        if norm in seen:
            continue
        seen.add(norm)
        tag = (
            await db.execute(
                select(Tag).where(Tag.owner_id == owner_id, Tag.name_normalized == norm)
            )
        ).scalar_one_or_none()
        if tag is None:
            tag = Tag(owner_id=owner_id, name=clean, name_normalized=norm)
            db.add(tag)
            await db.flush()
        tags.append(tag)
    return tags


async def set_tags_for(db: AsyncSession, set_id: str) -> list[str]:
    rows = (
        await db.execute(
            select(Tag.name)
            .join(SetTag, SetTag.tag_id == Tag.id)
            .where(SetTag.set_id == set_id)
            .order_by(Tag.name)
        )
    ).scalars().all()
    return list(rows)


async def replace_tags(db: AsyncSession, set_row: SetModel, names: list[str]) -> None:
    await db.execute(SetTag.__table__.delete().where(SetTag.set_id == set_row.id))
    tags = await _get_or_create_tags(db, set_row.owner_id, names)
    for t in tags:
        db.add(SetTag(set_id=set_row.id, tag_id=t.id))
    await db.flush()


async def create_set(db: AsyncSession, owner: User, payload: SetCreate) -> SetModel:
    st = SetModel(
        owner_id=owner.id,
        title=payload.title.strip(),
        description=payload.description.strip(),
        front_language=payload.front_language.strip().lower(),
        back_language=payload.back_language.strip().lower(),
        visibility=payload.visibility,
    )
    db.add(st)
    await db.flush()
    await replace_tags(db, st, payload.tags)
    limit = settings.max_cards_per_set
    if len(payload.cards) > limit:
        raise ApiError(413, "TOO_MANY_CARDS", f"Максимум карточек в наборе: {limit}.")
    for pos, card_in in enumerate(payload.cards):
        await _insert_card(db, st.id, pos, card_in)
    await bump_set_version(db, st.id)
    # Собственный набор попадает в библиотеку создателя.
    db.add(LibraryEntry(user_id=owner.id, set_id=st.id))
    await search_index.index_set_meta(db, st, payload.tags)
    await db.flush()
    return st


async def create_set_with_cards(
    db: AsyncSession,
    owner_id: str,
    title: str,
    description: str,
    front_language: str,
    back_language: str,
    tags: list[str],
    cards: list[dict],
) -> SetModel:
    payload = SetCreate(
        title=title,
        description=description,
        front_language=front_language,
        back_language=back_language,
        tags=tags,
        cards=[CardIn(**c) for c in cards],
    )
    owner = User(id=owner_id)
    return await create_set(db, owner, payload)


async def _insert_card(db: AsyncSession, set_id: str, position: int, card_in: CardIn, card_id: str | None = None) -> Card:
    from app.models import AcceptedAnswer

    fields = dict(
        set_id=set_id,
        position=position,
        front_text=card_in.front_text,
        back_text=card_in.back_text,
        front_context=card_in.front_context,
        back_context=card_in.back_context,
        front_hint=card_in.front_hint,
        back_hint=card_in.back_hint,
        front_explanation=card_in.front_explanation,
        back_explanation=card_in.back_explanation,
        front_example=card_in.front_example,
        back_example=card_in.back_example,
        front_language=card_in.front_language,
        back_language=card_in.back_language,
        enabled_front_to_back=card_in.enabled_front_to_back,
        enabled_back_to_front=card_in.enabled_back_to_front,
        written_check_front=card_in.written_check_front,
        written_check_back=card_in.written_check_back,
    )
    if card_id:
        fields["id"] = card_id
    card = Card(**fields)
    db.add(card)
    await db.flush()
    for side_key, answers in (("front", card_in.accepted_front), ("back", card_in.accepted_back)):
        for i, answer in enumerate(answers):
            clean = answer.strip()
            if not clean:
                continue
            db.add(AcceptedAnswer(card_id=card.id, side=side_key, answer=clean[:10000], position=i))
    await db.flush()
    await search_index.index_card(db, set_id, card)
    return card


async def copy_set(db: AsyncSession, user: User, source: SetModel) -> SetModel:
    """Копия создаёт новые ID; медиа переиспользуются (ссылки), прогресс не копируется."""
    tags = await set_tags_for(db, source.id)
    cards = (
        await db.execute(
            select(Card)
            .options(selectinload(Card.accepted_answers))
            .where(Card.set_id == source.id, Card.deleted_at.is_(None))
            .order_by(Card.position)
        )
    ).scalars().all()
    new_set = SetModel(
        owner_id=user.id,
        title=f"{source.title} (копия)"[:300],
        description=source.description,
        front_language=source.front_language,
        back_language=source.back_language,
        visibility="private",
    )
    db.add(new_set)
    await db.flush()
    for t in await _get_or_create_tags(db, user.id, tags):
        db.add(SetTag(set_id=new_set.id, tag_id=t.id))
    from app.models import AcceptedAnswer, CardMedia

    for pos, card in enumerate(cards):
        new_card = Card(
            set_id=new_set.id,
            position=pos,
            front_text=card.front_text,
            back_text=card.back_text,
            front_context=card.front_context,
            back_context=card.back_context,
            front_hint=card.front_hint,
            back_hint=card.back_hint,
            front_explanation=card.front_explanation,
            back_explanation=card.back_explanation,
            front_example=card.front_example,
            back_example=card.back_example,
            front_language=card.front_language,
            back_language=card.back_language,
            enabled_front_to_back=card.enabled_front_to_back,
            enabled_back_to_front=card.enabled_back_to_front,
            written_check_front=card.written_check_front,
            written_check_back=card.written_check_back,
        )
        db.add(new_card)
        await db.flush()
        for aa in card.accepted_answers:
            db.add(AcceptedAnswer(card_id=new_card.id, side=aa.side, answer=aa.answer, position=aa.position))
        media_rows = (
            await db.execute(select(CardMedia).where(CardMedia.card_id == card.id))
        ).scalars().all()
        for m in media_rows:
            db.add(CardMedia(card_id=new_card.id, side=m.side, media_id=m.media_id, position=m.position))
        await search_index.index_card(db, new_set.id, new_card)
    await search_index.index_set_meta(db, new_set, tags)
    await bump_set_version(db, new_set.id)
    db.add(LibraryEntry(user_id=user.id, set_id=new_set.id))
    await db.flush()
    return new_set


async def card_count(db: AsyncSession, set_id: str) -> int:
    return (
        await db.execute(
            select(func.count()).select_from(Card).where(Card.set_id == set_id, Card.deleted_at.is_(None))
        )
    ).scalar_one()


def _due_count_expression():
    return None


async def get_set_list_items(
    db: AsyncSession,
    user: User,
    set_ids: list[str],
    viewer_scope: str,
) -> list[dict]:
    """Массовые метаданные для списка наборов (без N+1)."""
    if not set_ids:
        return []
    rows = (
        await db.execute(
            select(
                SetModel,
                User.username,
                User.role.label("owner_role"),
                LibraryEntry.is_favorite,
                LibraryEntry.user_id.label("lib_user"),
                LibraryEntry.last_studied_at,
            )
            .join(User, User.id == SetModel.owner_id)
            .outerjoin(LibraryEntry, (LibraryEntry.set_id == SetModel.id) & (LibraryEntry.user_id == user.id))
            .where(SetModel.id.in_(set_ids))
        )
    ).all()
    counts = dict(
        (
            await db.execute(
                select(Card.set_id, func.count())
                .where(Card.set_id.in_(set_ids), Card.deleted_at.is_(None))
                .group_by(Card.set_id)
            )
        ).all()
    )
    tag_rows = (
        await db.execute(
            select(SetTag.set_id, Tag.name).join(Tag, Tag.id == SetTag.tag_id).where(SetTag.set_id.in_(set_ids))
        )
    ).all()
    tags_by_set: dict[str, list[str]] = {}
    for set_id, name in tag_rows:
        tags_by_set.setdefault(set_id, []).append(name)
    folder_rows = (
        await db.execute(
            select(FolderSet.set_id, FolderSet.folder_id).where(
                FolderSet.set_id.in_(set_ids), FolderSet.folder_id.in_(
                    select(FolderSet.folder_id).where(FolderSet.set_id.in_(set_ids))
                )
            )
        )
    ).all()
    # folder membership only for viewer's folders
    from app.models import Folder

    viewer_folders = (
        await db.execute(select(Folder.id).where(Folder.user_id == user.id))
    ).scalars().all()
    viewer_folder_set = set(viewer_folders)
    folders_by_set: dict[str, str] = {}
    for set_id, folder_id in folder_rows:
        if folder_id in viewer_folder_set:
            folders_by_set[set_id] = folder_id
    enrollments = {
        r[0]: r
        for r in (
            await db.execute(
                select(SrsEnrollment.set_id, SrsEnrollment.enabled).where(
                    SrsEnrollment.user_id == user.id, SrsEnrollment.set_id.in_(set_ids)
                )
            )
        ).all()
    }
    out = []
    for st, owner_username, owner_role, is_favorite, lib_user, last_studied in rows:
        enrolled = enrollments.get(st.id)
        out.append(
            {
                "id": st.id,
                "title": st.title,
                "description": st.description,
                "front_language": st.front_language,
                "back_language": st.back_language,
                "visibility": st.visibility,
                "archived": st.archived,
                "tags": tags_by_set.get(st.id, []),
                "card_count": counts.get(st.id, 0),
                "owner_username": owner_username,
                "is_own": st.owner_id == user.id,
                "is_admin_created": owner_role == "admin",
                "is_favorite": bool(is_favorite),
                "in_library": lib_user is not None,
                "in_folder_id": folders_by_set.get(st.id),
                "last_studied_at": last_studied,
                "created_at": st.created_at,
                "updated_at": st.updated_at,
                "due_count": None if not enrolled or not enrolled[1] else 0,
                "srs_enabled": bool(enrolled and enrolled[1]),
                "content_version": st.content_version,
            }
        )
    return out


async def archive_set(db: AsyncSession, st: SetModel, archived: bool) -> None:
    st.archived = archived
    st.archived_at = utcnow() if archived else None
    st.updated_at = utcnow()
    await db.commit()


async def delete_set(db: AsyncSession, st: SetModel) -> None:
    """Soft-delete: история (снимки) остаётся, активная очередь повторения очищается."""
    st.deleted_at = utcnow()
    st.updated_at = utcnow()
    await db.execute(update(Card).where(Card.set_id == st.id).values(deleted_at=utcnow()))
    await search_index.remove_set(db, st.id)
    from app.services import srs_service

    await srs_service.on_set_deleted(db, user_id=st.owner_id, set_id=st.id)
    await db.commit()
