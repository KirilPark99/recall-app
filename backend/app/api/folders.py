"""Папки и теги (личная организация)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.errors import ApiError
from app.models import Folder, FolderSet, SetTag, Tag, User
from app.schemas.sets import FolderCreate, FolderOut, FolderPatch, TagOut

router = APIRouter(tags=["organize"])


@router.get("/folders", response_model=list[FolderOut])
async def list_folders(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (
        await db.execute(
            select(Folder, func.count(FolderSet.set_id))
            .outerjoin(FolderSet, FolderSet.folder_id == Folder.id)
            .where(Folder.user_id == user.id)
            .group_by(Folder.id)
            .order_by(Folder.name)
        )
    ).all()
    return [
        FolderOut(
            id=f.id,
            name=f.name,
            set_count=count,
            created_at=f.created_at,
            created_by_admin=f.created_by_admin,
        )
        for f, count in rows
    ]


@router.post("/folders", response_model=FolderOut, status_code=201)
async def create_folder(
    payload: FolderCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    name = payload.name.strip()
    exists = (
        await db.execute(select(Folder).where(Folder.user_id == user.id, Folder.name == name))
    ).scalar_one_or_none()
    if exists:
        raise ApiError(409, "FOLDER_EXISTS", "Папка с таким названием уже есть.")
    folder = Folder(user_id=user.id, name=name, created_by_admin=False)
    db.add(folder)
    await db.commit()
    await db.refresh(folder)
    return FolderOut(
        id=folder.id,
        name=folder.name,
        set_count=0,
        created_at=folder.created_at,
        created_by_admin=folder.created_by_admin,
    )


@router.patch("/folders/{folder_id}", response_model=FolderOut)
async def rename_folder(
    folder_id: str,
    payload: FolderPatch,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    folder = await _own_folder(db, user, folder_id)
    if folder.created_by_admin and user.role != "admin":
        raise ApiError(403, "FORBIDDEN", "Папку, созданную администратором, нельзя переименовывать.")
    name = payload.name.strip()
    exists = (
        await db.execute(
            select(Folder).where(Folder.user_id == user.id, Folder.name == name, Folder.id != folder.id)
        )
    ).scalar_one_or_none()
    if exists:
        raise ApiError(409, "FOLDER_EXISTS", "Папка с таким названием уже есть.")
    folder.name = name
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ApiError(409, "FOLDER_EXISTS", "Папка с таким названием уже есть.") from exc
    count = (
        await db.execute(select(func.count()).select_from(FolderSet).where(FolderSet.folder_id == folder.id))
    ).scalar_one()
    return FolderOut(
        id=folder.id,
        name=folder.name,
        set_count=count,
        created_at=folder.created_at,
        created_by_admin=folder.created_by_admin,
    )


@router.delete("/folders/{folder_id}")
async def delete_folder(
    folder_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    folder = await _own_folder(db, user, folder_id)
    if folder.created_by_admin and user.role != "admin":
        raise ApiError(403, "FORBIDDEN", "Папку, созданную администратором, нельзя удалять.")

    if user.role == "admin":
        assigned_folders = (
            await db.execute(
                select(Folder).where(
                    Folder.name == folder.name,
                    Folder.created_by_admin.is_(True),
                    Folder.id != folder.id,
                )
            )
        ).scalars().all()
        for af in assigned_folders:
            await db.execute(delete(FolderSet).where(FolderSet.folder_id == af.id))
            await db.delete(af)

    # Связи удаляются, наборы остаются.
    await db.execute(delete(FolderSet).where(FolderSet.folder_id == folder.id))
    await db.delete(folder)
    await db.commit()
    return {"ok": True}


@router.put("/folders/{folder_id}/sets/{set_id}")
async def add_set_to_folder(
    folder_id: str,
    set_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    folder = await _own_folder(db, user, folder_id)
    if folder.created_by_admin and user.role != "admin":
        raise ApiError(403, "FORBIDDEN", "Содержимое папки, созданной администратором, нельзя изменять.")
    from app.services.access import get_set_access

    await get_set_access(db, user, set_id)
    exists = (
        await db.execute(
            select(FolderSet).where(FolderSet.folder_id == folder.id, FolderSet.set_id == set_id)
        )
    ).scalar_one_or_none()
    if exists is None:
        db.add(FolderSet(folder_id=folder.id, set_id=set_id))
        await db.commit()
    return {"ok": True}


@router.delete("/folders/{folder_id}/sets/{set_id}")
async def remove_set_from_folder(
    folder_id: str,
    set_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    folder = await _own_folder(db, user, folder_id)
    if folder.created_by_admin and user.role != "admin":
        raise ApiError(403, "FORBIDDEN", "Содержимое папки, созданной администратором, нельзя изменять.")
    await db.execute(delete(FolderSet).where(FolderSet.folder_id == folder_id, FolderSet.set_id == set_id))
    await db.commit()
    return {"ok": True}


async def _own_folder(db: AsyncSession, user: User, folder_id: str) -> Folder:
    folder = (
        await db.execute(select(Folder).where(Folder.id == folder_id, Folder.user_id == user.id))
    ).scalar_one_or_none()
    if folder is None:
        raise ApiError(404, "NOT_FOUND", "Папка не найдена.")
    return folder


@router.get("/tags", response_model=list[TagOut])
async def list_tags(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    rows = (
        await db.execute(
            select(Tag, func.count(SetTag.set_id))
            .outerjoin(SetTag, SetTag.tag_id == Tag.id)
            .where(Tag.owner_id == user.id)
            .group_by(Tag.id)
            .order_by(Tag.name)
        )
    ).all()
    return [TagOut(id=t.id, name=t.name, set_count=count) for t, count in rows]


@router.patch("/tags/{tag_id}", response_model=TagOut)
async def rename_tag(
    tag_id: str,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    name = str(payload.get("name", "")).strip()[:64]
    if not name:
        raise ApiError(422, "VALIDATION_ERROR", "Название тега обязательно.")
    tag = (
        await db.execute(select(Tag).where(Tag.id == tag_id, Tag.owner_id == user.id))
    ).scalar_one_or_none()
    if tag is None:
        raise ApiError(404, "NOT_FOUND", "Тег не найден.")
    exists = (
        await db.execute(
            select(Tag).where(
                Tag.owner_id == user.id,
                Tag.name_normalized == name.lower(),
                Tag.id != tag.id,
            )
        )
    ).scalar_one_or_none()
    if exists:
        raise ApiError(409, "TAG_EXISTS", "Тег с таким названием уже есть.")
    tag.name = name
    tag.name_normalized = name.lower()
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ApiError(409, "TAG_EXISTS", "Тег с таким названием уже есть.") from exc
    count = (
        await db.execute(select(func.count()).select_from(SetTag).where(SetTag.tag_id == tag.id))
    ).scalar_one()
    return TagOut(id=tag.id, name=tag.name, set_count=count)


@router.delete("/tags/{tag_id}")
async def delete_tag(
    tag_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    tag = (
        await db.execute(select(Tag).where(Tag.id == tag_id, Tag.owner_id == user.id))
    ).scalar_one_or_none()
    if tag is None:
        raise ApiError(404, "NOT_FOUND", "Тег не найден.")
    await db.execute(delete(SetTag).where(SetTag.tag_id == tag.id))
    await db.delete(tag)
    await db.commit()
    return {"ok": True}
