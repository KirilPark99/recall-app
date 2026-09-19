"""Наборы: каталог, CRUD, копирование, архив, библиотека, избранное."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.config import settings
from app.core.errors import ApiError
from app.models import (
    Folder, FolderSet, LibraryEntry, SetModel, SetTag, SrsEnrollment, Tag, User,
)
from app.schemas.sets import (
    OperationResult, SetCreate, SetDetail, SetListItem, SetOut, SetPatch,
)
from app.services import search as search_index
from app.services import sets_service
from app.services.access import get_set_access, require_owner, visible_sets_condition

router = APIRouter(tags=["sets"])

SORT_WHITELIST = {"title", "updated", "last_studied", "cards", "created"}


@router.get("/sets", response_model=list[SetListItem])
async def list_sets(
    q: str | None = Query(default=None, max_length=200),
    tag: str | None = Query(default=None, max_length=64),
    folder_id: str | None = None,
    favorite: bool | None = None,
    archived: bool = False,
    srs: bool | None = None,
    language: str | None = Query(default=None, max_length=16),
    sort: str = Query(default="updated"),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1),
    page_size: int | None = Query(default=None, ge=1),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if sort not in SORT_WHITELIST:
        raise ApiError(422, "VALIDATION_ERROR", "Недопустимая сортировка.")
    page_size = min(page_size or settings.page_default_size, settings.page_max_size)
    conds = [visible_sets_condition(user), SetModel.deleted_at.is_(None), SetModel.archived == archived]
    if tag:
        conds.append(
            SetModel.id.in_(
                select(SetTag.set_id).join(Tag, Tag.id == SetTag.tag_id).where(Tag.name_normalized == tag.lower())
            )
        )
    if folder_id:
        if folder_id in ("unassigned", "none", "__none__"):
            conds.append(
                SetModel.id.not_in(
                    select(FolderSet.set_id).join(Folder, Folder.id == FolderSet.folder_id).where(
                        Folder.user_id == user.id
                    )
                )
            )
        elif folder_id != "all":
            conds.append(
                SetModel.id.in_(
                    select(FolderSet.set_id).join(Folder, Folder.id == FolderSet.folder_id).where(
                        Folder.user_id == user.id, FolderSet.folder_id == folder_id
                    )
                )
            )
    if language:
        conds.append(
            (SetModel.front_language == language.lower()) | (SetModel.back_language == language.lower())
        )
    if q:
        ids = await search_index.search_set_ids(db, q, None)
        if not ids:
            return []
        conds.append(SetModel.id.in_(ids))
    base_q = select(SetModel.id).where(and_(*conds))
    # ponytail: list metadata is assembled in Python; move aggregates into SQL if set counts become large.
    rows = (await db.execute(base_q)).scalars().all()
    items = await sets_service.get_set_list_items(db, user, list(rows), "mixed")
    reverse = order == "desc"
    if sort == "title":
        items.sort(key=lambda x: x["title"].lower(), reverse=reverse)
    elif sort == "cards":
        items.sort(key=lambda x: x["card_count"], reverse=reverse)
    elif sort == "last_studied":
        items.sort(key=lambda x: (x["last_studied_at"] is not None, x["last_studied_at"]), reverse=reverse)
    elif sort == "created":
        items.sort(key=lambda x: x["created_at"], reverse=reverse)
    elif sort == "updated":
        items.sort(key=lambda x: x["updated_at"], reverse=reverse)
    if favorite is not None:
        items = [x for x in items if x["is_favorite"] == favorite]
    if srs is not None:
        items = [x for x in items if bool(x.get("srs_enabled")) == srs]
    items = items[(page - 1) * page_size:page * page_size]
    return [SetListItem(**x) for x in items]


@router.post("/sets", response_model=SetDetail, status_code=201)
async def create_set(
    payload: SetCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    st = await sets_service.create_set(db, user, payload)
    await db.commit()
    return await get_set_detail(db, user, st.id)


@router.get("/sets/{set_id}", response_model=SetDetail)
async def get_set(
    set_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    return await get_set_detail(db, user, set_id)


async def get_set_detail(db: AsyncSession, user: User, set_id: str) -> SetDetail:
    access = await get_set_access(db, user, set_id)
    st = access.set
    items = await sets_service.get_set_list_items(db, user, [st.id], "one")
    base = items[0] if items else {}
    folder_rows = (
        await db.execute(
            select(Folder.id, Folder.name)
            .join(FolderSet, FolderSet.folder_id == Folder.id)
            .where(Folder.user_id == user.id, FolderSet.set_id == st.id)
        )
    ).all()
    return SetDetail(**base, viewer_role=access.role.value, folders=[name for _i, name in folder_rows])


@router.patch("/sets/{set_id}", response_model=OperationResult)
async def patch_set(
    set_id: str,
    payload: SetPatch,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    st = await require_owner(db, user, set_id)
    old_visibility = st.visibility
    data = payload.model_dump(exclude_unset=True)
    expected = data.pop("expected_content_version")
    if st.content_version != expected:
        raise ApiError(
            409,
            "SET_VERSION_CONFLICT",
            "Набор изменился в другой вкладке.",
            {"current_content_version": st.content_version},
        )
    tags = data.pop("tags", None)
    for key, value in data.items():
        if key in ("front_language", "back_language") and value is not None:
            value = value.strip().lower()
        setattr(st, key, value)
    if tags is not None:
        await sets_service.replace_tags(db, st, tags)
    new_version = await sets_service.bump_set_version(db, st.id)
    await search_index.index_set_meta(db, st, await sets_service.set_tags_for(db, st.id))
    if old_visibility != st.visibility and st.visibility == "private":
        from app.services.share_service import revoke_links_on_privatize

        await revoke_links_on_privatize(db, st)
    await db.commit()
    return OperationResult(content_version=new_version)


@router.delete("/sets/{set_id}")
async def delete_set(
    set_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    st = await require_owner(db, user, set_id)
    await sets_service.delete_set(db, st)
    return {"ok": True}


@router.post("/sets/{set_id}/copy", response_model=SetOut, status_code=201)
async def copy_set(
    set_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    access = await get_set_access(db, user, set_id)
    new_set = await sets_service.copy_set(db, user, access.set)
    await db.commit()
    return SetOut.model_validate(new_set)


@router.post("/sets/{set_id}/archive", response_model=OperationResult)
async def archive_set(
    set_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    st = await require_owner(db, user, set_id)
    await sets_service.archive_set(db, st, True)
    return OperationResult(content_version=st.content_version)


@router.post("/sets/{set_id}/restore", response_model=OperationResult)
async def restore_set(
    set_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    st = await require_owner(db, user, set_id)
    await sets_service.archive_set(db, st, False)
    return OperationResult(content_version=st.content_version)


@router.put("/sets/{set_id}/favorite")
async def set_favorite(
    set_id: str,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    enabled = payload.get("enabled")
    if not isinstance(enabled, bool):
        raise ApiError(422, "VALIDATION_ERROR", "Поле enabled обязательно.")
    await get_set_access(db, user, set_id)
    entry = (
        await db.execute(
            select(LibraryEntry).where(LibraryEntry.user_id == user.id, LibraryEntry.set_id == set_id)
        )
    ).scalar_one_or_none()
    if entry is None:
        raise ApiError(404, "NOT_FOUND", "Набор не находится в вашей библиотеке.")
    entry.is_favorite = enabled
    await db.commit()
    return {"ok": True, "enabled": enabled}


@router.post("/library/sets/{set_id}", status_code=201)
async def add_to_library(
    set_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    """«Добавить в мои наборы»: ссылка + личные настройки, без копирования контента."""
    await get_set_access(db, user, set_id)
    exists = (
        await db.execute(
            select(LibraryEntry).where(LibraryEntry.user_id == user.id, LibraryEntry.set_id == set_id)
        )
    ).scalar_one_or_none()
    if exists is None:
        db.add(LibraryEntry(user_id=user.id, set_id=set_id))
        await db.commit()
    return {"ok": True}


@router.delete("/library/sets/{set_id}")
async def remove_from_library(
    set_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    entry = (
        await db.execute(
            select(LibraryEntry).where(LibraryEntry.user_id == user.id, LibraryEntry.set_id == set_id)
        )
    ).scalar_one_or_none()
    if entry is None:
        raise ApiError(404, "NOT_FOUND", "Набор не находится в вашей библиотеке.")
    if user.role != "admin":
        st = (await db.execute(select(SetModel).where(SetModel.id == set_id))).scalar_one_or_none()
        if st:
            owner = (await db.execute(select(User).where(User.id == st.owner_id))).scalar_one_or_none()
            if owner and owner.role == "admin":
                raise ApiError(403, "FORBIDDEN", "Наборы, назначенные администратором, нельзя удалить из библиотеки.")
    await db.delete(entry)
    from sqlalchemy import update as sql_update

    await db.execute(
        sql_update(SrsEnrollment)
        .where(SrsEnrollment.user_id == user.id, SrsEnrollment.set_id == set_id)
        .values(enabled=False)
    )
    await db.commit()
    return {"ok": True}
