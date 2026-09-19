"""Карточки: списки, батчи, порядок, массовые операции, смена сторон, звёздочка."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.errors import ApiError
from app.models import SetModel, User, UserCardFlag
from app.schemas.sets import (
    BatchCardsIn, BulkIdsIn, BulkMoveIn, CardListOut, CardOut, CardPatch,
    OperationResult, ReorderIn, SwapSidesIn,
)
from app.services import cards_service, sets_service
from app.services.access import Role, get_card_access, get_set_access
from app.services.card_dto import build_card_dtos

router = APIRouter(tags=["cards"])


@router.get("/sets/{set_id}/cards", response_model=CardListOut)
async def list_cards(
    set_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int | None = Query(default=None, ge=1),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await get_set_access(db, user, set_id)
    from app.core.config import settings

    size = min(page_size or settings.page_default_size, settings.page_max_size)
    cards, total = await cards_service.list_cards_dto(db, user.id, set_id, size, (page - 1) * size)
    st = (await db.execute(select(SetModel).where(SetModel.id == set_id))).scalar_one()
    return CardListOut(
        items=await build_card_dtos(db, user.id, cards),
        total=total,
        set_content_version=st.content_version,
    )


@router.post("/sets/{set_id}/cards/batch", response_model=OperationResult, status_code=201)
async def create_cards_batch(
    set_id: str,
    payload: BatchCardsIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    access = await get_set_access(db, user, set_id)
    if access.role != Role.OWNER:
        raise ApiError(403, "FORBIDDEN", "Только владелец может изменять набор.")
    count = await cards_service.card_count_of(db, set_id)
    from app.core.config import settings

    if count + len(payload.cards) > settings.max_cards_per_set:
        raise ApiError(413, "TOO_MANY_CARDS", f"Максимум карточек в наборе: {settings.max_cards_per_set}.")
    start_pos = count
    for i, card_in in enumerate(payload.cards):
        if not card_in.front_text.strip() and not card_in.back_text.strip():
            raise ApiError(422, "VALIDATION_ERROR", f"Карточка {i + 1}: обе стороны пусты.")
        await cards_service.create_card(db, access.set, card_in, at_position=start_pos + i)
    version = await sets_service.bump_set_version(db, set_id, payload.expected_content_version)
    await db.commit()
    return OperationResult(content_version=version, applied=len(payload.cards))


@router.post("/sets/{set_id}/cards", response_model=CardOut, status_code=201)
async def create_card(
    set_id: str,
    payload: CardPatch,
    at_position: int | None = Query(default=None, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    access = await get_set_access(db, user, set_id)
    if access.role != Role.OWNER:
        raise ApiError(403, "FORBIDDEN", "Только владелец может изменять набор.")
    card = await cards_service.create_card(db, access.set, payload, at_position)
    await sets_service.bump_set_version(db, set_id)
    await db.commit()
    card = await cards_service.get_card(db, card.id)  # с accepted_answers (selectinload)
    (dto,) = await build_card_dtos(db, user.id, [card])
    return dto


@router.patch("/sets/{set_id}/cards/{card_id}", response_model=CardOut)
async def patch_card(
    set_id: str,
    card_id: str,
    payload: CardPatch,
    expected_content_version: int | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await require_owner_set(db, user, set_id)
    card = await cards_service.get_card(db, card_id)
    if expected_content_version is not None:
        st = (await db.execute(select(SetModel).where(SetModel.id == set_id))).scalar_one()
        if st.content_version != expected_content_version:
            from app.core.errors import ApiError

            raise ApiError(
                409,
                "SET_VERSION_CONFLICT",
                "Набор изменился в другой вкладке.",
                {"current_content_version": st.content_version},
            )
    if card.set_id != set_id:
        raise ApiError(404, "NOT_FOUND", "Карточка не найдена в этом наборе.")
    await cards_service.apply_card_patch(db, card, payload)
    await sets_service.bump_set_version(db, set_id)
    await db.commit()
    (dto,) = await build_card_dtos(db, user.id, [card])
    return dto


async def require_owner_set(db: AsyncSession, user: User, set_id: str) -> SetModel:
    from app.services.access import require_owner

    return await require_owner(db, user, set_id)


@router.delete("/sets/{set_id}/cards/{card_id}", response_model=OperationResult)
async def delete_card(
    set_id: str,
    card_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await require_owner_set(db, user, set_id)
    card = await cards_service.get_card(db, card_id)
    if card.set_id != set_id:
        raise ApiError(404, "NOT_FOUND", "Карточка не найдена в этом наборе.")
    await cards_service.delete_card(db, card)
    version = await sets_service.bump_set_version(db, set_id)
    await db.commit()
    return OperationResult(content_version=version, applied=1)


@router.post("/sets/{set_id}/cards/{card_id}/restore", response_model=CardOut)
async def restore_card(
    set_id: str,
    card_id: str,
    at_position: int | None = Query(default=None, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await require_owner_set(db, user, set_id)
    card = await cards_service.get_deleted_card(db, card_id)
    if card.set_id != set_id:
        raise ApiError(404, "NOT_FOUND", "Карточка не найдена в этом наборе.")
    await cards_service.restore_card(db, card, at_position)
    await sets_service.bump_set_version(db, set_id)
    await db.commit()
    (dto,) = await build_card_dtos(db, user.id, [card])
    return dto


@router.post("/sets/{set_id}/cards/{card_id}/duplicate", response_model=CardOut, status_code=201)
async def duplicate_card(
    set_id: str,
    card_id: str,
    at_position: int | None = Query(default=None, ge=0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    st = await require_owner_set(db, user, set_id)
    source = await cards_service.get_card(db, card_id)
    if source.set_id != set_id:
        raise ApiError(404, "NOT_FOUND", "Карточка не найдена в этом наборе.")
    card = await cards_service.duplicate_card(db, st, source, at_position)
    await sets_service.bump_set_version(db, set_id)
    await db.commit()
    card = await cards_service.get_card(db, card.id)
    (dto,) = await build_card_dtos(db, user.id, [card])
    return dto


@router.post("/sets/{set_id}/cards/reorder", response_model=OperationResult)
async def reorder_cards(
    set_id: str,
    payload: ReorderIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await require_owner_set(db, user, set_id)
    await cards_service.reorder_cards(db, access_set(db, user, set_id), payload.ordered_ids)
    version = await sets_service.bump_set_version(db, set_id, payload.expected_content_version)
    await db.commit()
    return OperationResult(content_version=version, applied=len(payload.ordered_ids))


def access_set(db: AsyncSession, user: User, set_id: str) -> SetModel:
    # Синхронная заглушка: доступ уже проверен require_owner_set.
    return SetModel(id=set_id, owner_id=user.id)


@router.post("/sets/{set_id}/cards/bulk-delete", response_model=OperationResult)
async def bulk_delete(
    set_id: str,
    payload: BulkIdsIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await require_owner_set(db, user, set_id)
    applied = await cards_service.bulk_delete(db, access_set(db, user, set_id), payload.card_ids)
    version = await sets_service.bump_set_version(db, set_id, payload.expected_content_version)
    await db.commit()
    return OperationResult(content_version=version, applied=applied)


@router.post("/sets/{set_id}/cards/bulk-move", response_model=OperationResult)
async def bulk_move(
    set_id: str,
    payload: BulkMoveIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await require_owner_set(db, user, set_id)
    target = await require_owner_set(db, user, payload.target_set_id)
    if target.content_version != payload.target_expected_content_version:
        raise ApiError(
            409,
            "SET_VERSION_CONFLICT",
            "Целевой набор изменился.",
            {"current_content_version": target.content_version},
        )
    source_count = await cards_service.bulk_move(db, access_set(db, user, set_id), target, payload.card_ids)
    v1 = await sets_service.bump_set_version(db, set_id, payload.expected_content_version)
    v2 = await sets_service.bump_set_version(db, target.id)
    await db.commit()
    return OperationResult(content_version=v1, applied=source_count, ok=v2 > 0)


@router.post("/sets/{set_id}/cards/swap-sides", response_model=OperationResult)
async def swap_sides(
    set_id: str,
    payload: SwapSidesIn | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    st = await require_owner_set(db, user, set_id)
    from app.services.cards_service import swap_sides as swap

    applied = await swap(db, st)
    st.front_language, st.back_language = st.back_language, st.front_language
    expected = payload.expected_content_version if payload else None
    version = await sets_service.bump_set_version(db, set_id, expected)
    await db.commit()
    return OperationResult(content_version=version, applied=applied)


@router.post("/sets/{set_id}/cards/{card_id}/swap-sides", response_model=OperationResult)
async def swap_card_sides(
    set_id: str,
    card_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.core.errors import ApiError

    await require_owner_set(db, user, set_id)
    card = await cards_service.get_card(db, card_id)
    if card.set_id != set_id:
        raise ApiError(404, "NOT_FOUND", "Карточка не найдена в этом наборе.")
    await cards_service.swap_single_card_sides(db, card)
    version = await sets_service.bump_set_version(db, set_id, None)
    await db.commit()
    return OperationResult(content_version=version, applied=1)




class MediaAttachIn(BaseModel):
    media_id: str
    side: str


@router.post("/sets/{set_id}/cards/{card_id}/media", status_code=201)
async def attach_media(
    set_id: str,
    card_id: str,
    payload: MediaAttachIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.models import CardMedia as CM, Media as MediaModel
    from app.core.errors import ApiError

    await require_owner_set(db, user, set_id)
    card = await cards_service.get_card(db, card_id)
    if card.set_id != set_id:
        raise ApiError(404, "NOT_FOUND", "Карточка не найдена в этом наборе.")
    if payload.side not in ("front", "back"):
        raise ApiError(422, "VALIDATION_ERROR", "Сторона: front или back.")
    media = (
        await db.execute(
            select(MediaModel).where(
                MediaModel.id == payload.media_id,
                MediaModel.owner_id == user.id,
                MediaModel.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if media is None:
        raise ApiError(404, "NOT_FOUND", "Файл не найден.")
    count = (
        await db.execute(select(func.count()).select_from(CM).where(CM.card_id == card.id, CM.side == payload.side))
    ).scalar_one()
    if count >= 4:
        raise ApiError(422, "TOO_MANY_MEDIA", "Не больше 4 файлов на сторону.")
    exists = (
        await db.execute(
            select(CM).where(CM.card_id == card.id, CM.side == payload.side, CM.media_id == media.id)
        )
    ).scalar_one_or_none()
    if exists is None:
        db.add(CM(card_id=card.id, side=payload.side, media_id=media.id, position=count))
        await db.commit()
    (dto,) = await build_card_dtos(db, user.id, [card])
    return dto


@router.delete("/sets/{set_id}/cards/{card_id}/media/{media_id}")
async def detach_media(
    set_id: str,
    card_id: str,
    media_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.models import CardMedia as CM
    from app.core.errors import ApiError

    await require_owner_set(db, user, set_id)
    card = await cards_service.get_card(db, card_id)
    if card.set_id != set_id:
        raise ApiError(404, "NOT_FOUND", "Карточка не найдена в этом наборе.")
    await db.execute(CM.__table__.delete().where(CM.card_id == card.id, CM.media_id == media_id))
    await sets_service.bump_set_version(db, set_id)
    await db.commit()
    (dto,) = await build_card_dtos(db, user.id, [card])
    return dto


@router.put("/cards/{card_id}/star")
async def star_card(
    card_id: str,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    enabled = payload.get("enabled")
    if enabled is None:
        enabled = payload.get("starred")
    if not isinstance(enabled, bool):
        raise ApiError(422, "VALIDATION_ERROR", "Поле enabled (или starred) обязательно.")
    # Личная звёздочка доступна и читателю (изучающему).
    await get_card_access(db, user, card_id)
    flag = (
        await db.execute(
            select(UserCardFlag).where(UserCardFlag.user_id == user.id, UserCardFlag.card_id == card_id)
        )
    ).scalar_one_or_none()
    if flag is None:
        db.add(UserCardFlag(user_id=user.id, card_id=card_id, is_starred=enabled))
    else:
        flag.is_starred = enabled
    await db.commit()
    return {"ok": True, "enabled": enabled}
