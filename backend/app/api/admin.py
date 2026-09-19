"""Администрирование: пользователи, настройки, статус, аудит, backup."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_admin_user, get_db
from app.core.config import settings
from app.core.db import migrations_ready
from app.core.errors import ApiError
from app.core.security import hash_password
from app.db.base import utcnow
from app.models import (
    AuditEvent, Folder, FolderSet, LibraryEntry, Media, Session as DbSession,
    SetModel, SetPermission, SrsState, User,
)
from app.services.settings_service import ensure_defaults_for_user, get_setting, set_setting

router = APIRouter(prefix="/admin", tags=["admin"])


class AdminUserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=8, max_length=256)
    role: str = "user"


class AdminUserPatch(BaseModel):
    role: str | None = None
    is_active: bool | None = None


class ResetPasswordIn(BaseModel):
    new_password: str = Field(min_length=8, max_length=256)


class AdminSettingsPatch(BaseModel):
    registration_enabled: bool | None = None
    quizlet_proxy_url: str | None = None
    quizlet_headless: bool | None = None


class ProxyTestRequest(BaseModel):
    proxy_url: str | None = None


@router.get("/users")
async def list_users(
    q: str | None = Query(default=None, max_length=64),
    role: str | None = None,
    is_active: bool | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    conds = []
    if q:
        conds.append(User.username_normalized.like(f"%{q.lower()}%"))
    if role in ("admin", "user"):
        conds.append(User.role == role)
    if is_active is not None:
        conds.append(User.is_active == is_active)
    base = select(User).where(*conds).order_by(User.created_at)
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (await db.execute(base.offset((page - 1) * page_size).limit(page_size))).scalars().all()
    return {
        "total": total,
        "items": [
            {
                "id": u.id, "username": u.username, "role": u.role, "is_active": u.is_active,
                "created_at": u.created_at, "last_login_at": u.last_login_at,
                "set_count": (
                    await db.execute(select(func.count()).select_from(SetModel).where(SetModel.owner_id == u.id, SetModel.deleted_at.is_(None)))
                ).scalar_one(),
            }
            for u in rows
        ],
    }


@router.post("/users", status_code=201)
async def create_user(
    payload: AdminUserCreate, db: AsyncSession = Depends(get_db), admin: User = Depends(get_admin_user)
):
    normalized = payload.username.strip().lower()
    exists = (
        await db.execute(select(User.id).where(User.username_normalized == normalized))
    ).scalar_one_or_none()
    if exists:
        raise ApiError(409, "USERNAME_TAKEN", "Это имя пользователя уже занято.")
    user = User(
        username=payload.username.strip(),
        username_normalized=normalized,
        password_hash=hash_password(payload.password),
        role=payload.role if payload.role in ("admin", "user") else "user",
    )
    db.add(user)
    await db.flush()
    await ensure_defaults_for_user(db, user.id)
    db.add(AuditEvent(actor_id=admin.id, action="user_created", target_type="user", target_id=user.id))
    await db.commit()
    return {"ok": True, "user_id": user.id}


async def _protect_last_admin(db: AsyncSession, target: User, new_role: str | None, new_active: bool | None) -> None:
    if target.role == "admin" and (new_role == "user" or new_active is False):
        active_admins = (
            await db.execute(
                select(func.count()).select_from(User).where(User.role == "admin", User.is_active.is_(True))
            )
        ).scalar_one()
        if active_admins <= 1:
            raise ApiError(409, "LAST_ADMIN", "Нельзя понизить или заблокировать последнего активного администратора.")


@router.patch("/users/{user_id}")
async def patch_user(
    user_id: str,
    payload: AdminUserPatch,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    target = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if target is None:
        raise ApiError(404, "NOT_FOUND", "Пользователь не найден.")
    if payload.role is not None and payload.role not in ("admin", "user"):
        raise ApiError(422, "VALIDATION_ERROR", "Роль: admin или user.")
    await _protect_last_admin(db, target, payload.role, payload.is_active)
    blocked_now = target.is_active and payload.is_active is False
    if payload.role is not None:
        target.role = payload.role
    if payload.is_active is not None:
        target.is_active = payload.is_active
    if blocked_now:
        # Блокировка отзывает сессии в той же операции; наборы не удаляются.
        await db.execute(
            update(DbSession).where(DbSession.user_id == target.id, DbSession.revoked_at.is_(None)).values(revoked_at=utcnow())
        )
    db.add(AuditEvent(actor_id=admin.id, action="user_updated", target_type="user", target_id=target.id,
                      details_json=json.dumps({"role": payload.role, "is_active": payload.is_active})))
    await db.commit()
    return {"ok": True, "role": target.role, "is_active": target.is_active}


@router.post("/users/{user_id}/reset-password")
async def reset_password(
    user_id: str,
    payload: ResetPasswordIn,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    target = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if target is None:
        raise ApiError(404, "NOT_FOUND", "Пользователь не найден.")
    target.password_hash = hash_password(payload.new_password)
    # Сброс пароля отзывает сессии пользователя.
    await db.execute(
        update(DbSession).where(DbSession.user_id == target.id, DbSession.revoked_at.is_(None)).values(revoked_at=utcnow())
    )
    db.add(AuditEvent(actor_id=admin.id, action="password_reset", target_type="user", target_id=target.id))
    await db.commit()
    return {"ok": True}


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str, db: AsyncSession = Depends(get_db), admin: User = Depends(get_admin_user)
):
    target = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if target is None:
        raise ApiError(404, "NOT_FOUND", "Пользователь не найден.")
    if target.id == admin.id:
        raise ApiError(409, "SELF_DELETE", "Нельзя удалить свою учётную запись.")
    await _protect_last_admin(db, target, "user", None)
    # Судьба контента: наборы удаляются с владельцем (CASCADE), чужая числовая история обезличивается.
    await db.execute(
        update(DbSession).where(DbSession.user_id == target.id).values(revoked_at=utcnow())
    )
    db.add(AuditEvent(actor_id=admin.id, action="user_deleted", target_type="user", target_id=target.id,
                      details_json=json.dumps({"username": target.username})))
    await db.delete(target)
    await db.commit()
    return {"ok": True}


@router.get("/settings")
async def get_admin_settings(db: AsyncSession = Depends(get_db), admin: User = Depends(get_admin_user)):
    return {
        "registration_enabled": await get_setting(db, "registration_enabled", False),
        "quizlet_proxy_url": await get_setting(db, "quizlet_proxy_url", ""),
        "quizlet_headless": await get_setting(db, "quizlet_headless", True),
        "env_limits": {
            "max_image_bytes": settings.max_image_bytes,
            "max_audio_bytes": settings.max_audio_bytes,
            "max_import_bytes": settings.max_import_bytes,
            "max_cards_per_set": settings.max_cards_per_set,
            "max_test_questions": settings.max_test_questions,
            "note": "Значения задаются переменными окружения (.env) и меняются перезапуском.",
        },
        "session": {
            "ttl_seconds": settings.session_ttl_seconds,
            "note": "Время жизни сессии задаётся окружением; смена требует перезапуска.",
        },
    }


@router.patch("/settings")
async def patch_admin_settings(
    payload: AdminSettingsPatch, db: AsyncSession = Depends(get_db), admin: User = Depends(get_admin_user)
):
    audit_changes = {}
    if payload.registration_enabled is not None:
        await set_setting(db, "registration_enabled", payload.registration_enabled)
        audit_changes["registration_enabled"] = payload.registration_enabled

    if payload.quizlet_proxy_url is not None:
        proxy_clean = payload.quizlet_proxy_url.strip()
        await set_setting(db, "quizlet_proxy_url", proxy_clean)
        # В аудите маскируем пароль если есть
        p_parsed = urlparse(proxy_clean)
        masked_proxy = proxy_clean
        if p_parsed.password:
            masked_proxy = proxy_clean.replace(f":{p_parsed.password}@", ":***@")
        audit_changes["quizlet_proxy_url"] = masked_proxy

    if payload.quizlet_headless is not None:
        await set_setting(db, "quizlet_headless", payload.quizlet_headless)
        audit_changes["quizlet_headless"] = payload.quizlet_headless

    if audit_changes:
        db.add(AuditEvent(actor_id=admin.id, action="settings_changed",
                          details_json=json.dumps(audit_changes)))
        await db.commit()
    return await get_admin_settings(db=db, admin=admin)


@router.post("/proxy/test")
async def test_proxy(
    payload: ProxyTestRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """Проверяет работоспособность указанного или сохранённого прокси-сервера."""
    import httpx

    raw_proxy = payload.proxy_url.strip() if payload.proxy_url is not None else ""
    if not raw_proxy:
        raw_proxy = (await get_setting(db, "quizlet_proxy_url", "")).strip()

    if not raw_proxy:
        raise ApiError(400, "NO_PROXY_SPECIFIED", "Прокси-сервер не указан.")

    parsed = urlparse(raw_proxy)
    if parsed.scheme not in ("http", "https", "socks5", "socks5h"):
        raise ApiError(400, "INVALID_PROXY_SCHEME", "Поддерживаются протоколы http, https или socks5.")

    start_time = time.time()
    last_err: Exception | None = None

    # Попытка проверить через ipify / httpbin / quizlet
    test_urls = [
        ("https://api.ipify.org?format=json", "ip"),
        ("https://httpbin.org/ip", "origin"),
        ("https://quizlet.com/", None),
    ]

    for test_url, ip_key in test_urls:
        try:
            async with httpx.AsyncClient(proxy=raw_proxy, timeout=12.0) as client:
                resp = await client.get(test_url)
                latency_ms = round((time.time() - start_time) * 1000)
                if resp.status_code in (200, 301, 302, 403):
                    ip_val = ""
                    if ip_key:
                        try:
                            data = resp.json()
                            ip_val = data.get(ip_key, "")
                        except Exception:
                            pass
                    return {
                        "ok": True,
                        "ip": ip_val or "OK",
                        "latency_ms": latency_ms,
                        "status_code": resp.status_code,
                        "message": f"Прокси успешно ответил за {latency_ms} мс." + (f" Внешний IP: {ip_val}." if ip_val else ""),
                    }
        except Exception as e:
            last_err = e
            continue

    raise ApiError(
        400,
        "PROXY_FAILED",
        f"Не удалось подключиться через прокси: {str(last_err) if last_err else 'таймаут соединения'}",
    )


@router.get("/status")
async def status(db: AsyncSession = Depends(get_db), admin: User = Depends(get_admin_user)):
    db_path = settings.database_path
    db_size = db_path.stat().st_size if db_path.exists() else 0
    media_size = sum(f.stat().st_size for f in settings.media_dir.rglob("*") if f.is_file())
    user_count = (await db.execute(select(func.count()).select_from(User))).scalar_one()
    set_count = (await db.execute(select(func.count()).select_from(SetModel).where(SetModel.deleted_at.is_(None)))).scalar_one()
    media_count = (await db.execute(select(func.count()).select_from(Media).where(Media.deleted_at.is_(None)))).scalar_one()
    backup_files = sorted(settings.backups_dir.glob("*.tar.gz"), key=lambda p: p.stat().st_mtime, reverse=True)
    return {
        "app_version": "1.0.0",
        "env": settings.app_env,
        "migrations_applied": await migrations_ready(),
        "database": {"path": str(db_path.name), "size_bytes": db_size, "users": user_count, "sets": set_count},
        "media": {"count": media_count, "size_bytes": media_size},
        "last_backup": {"name": backup_files[0].name, "created_at": backup_files[0].stat().st_mtime} if backup_files else None,
    }


@router.get("/audit-events")
async def audit_events(
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    rows = (
        await db.execute(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit))
    ).scalars().all()
    return [
        {
            "id": a.id, "actor_id": a.actor_id, "action": a.action,
            "target_type": a.target_type, "target_id": a.target_id,
            "result": a.result, "created_at": a.created_at,
        }
        for a in rows
    ]


@router.post("/backups", status_code=201)
async def create_backup_job(db: AsyncSession = Depends(get_db), admin: User = Depends(get_admin_user)):
    """Создание backup через job (SQLite-backed); скачивание — отдельным endpoint."""
    from app.cli_backup import create_backup

    stamp = utcnow().strftime("%Y%m%dT%H%M%SZ")
    out = settings.backups_dir / f"recall-backup-{stamp}.tar.gz"
    # Sync-операция в job-потоке: один сервер, размер данных умеренный.
    path = await __import__("asyncio").get_running_loop().run_in_executor(None, create_backup, out)
    db.add(AuditEvent(actor_id=admin.id, action="backup_created", target_type="backup", target_id=path.name))
    await db.commit()
    return {"job_id": path.stem, "file": path.name, "size_bytes": path.stat().st_size, "status": "completed"}


@router.get("/backups")
async def list_backups(db: AsyncSession = Depends(get_db), admin: User = Depends(get_admin_user)):
    files = sorted(settings.backups_dir.glob("*.tar.gz"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [{"name": p.name, "size_bytes": p.stat().st_size} for p in files]


@router.get("/backups/{name}/download")
async def download_backup(
    name: str, db: AsyncSession = Depends(get_db), admin: User = Depends(get_admin_user)
):
    if "/" in name or ".." in name or not name.endswith(".tar.gz"):
        raise ApiError(422, "VALIDATION_ERROR", "Некорректное имя файла.")
    path = settings.backups_dir / name
    if not path.is_file():
        raise ApiError(404, "NOT_FOUND", "Backup не найден.")
    from fastapi.responses import FileResponse

    return FileResponse(path, media_type="application/gzip", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/maintenance/cleanup-sessions")
async def cleanup_sessions(db: AsyncSession = Depends(get_db), admin: User = Depends(get_admin_user)):
    result = await db.execute(
        delete(DbSession).where((DbSession.expires_at < utcnow()) | (DbSession.revoked_at.is_not(None)))
    )
    await db.commit()
    return {"deleted": result.rowcount}


class AdminAssignSetIn(BaseModel):
    set_id: str


class AdminFolderCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    set_ids: list[str] = Field(default_factory=list)


@router.get("/users/{user_id}/content")
async def get_user_content(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    target = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if target is None:
        raise ApiError(404, "NOT_FOUND", "Пользователь не найден.")

    # 1. User's folders with sets inside
    folders_rows = (
        await db.execute(
            select(Folder)
            .where(Folder.user_id == target.id)
            .order_by(Folder.created_at)
        )
    ).scalars().all()

    folder_ids = [f.id for f in folders_rows]
    fs_rows = []
    if folder_ids:
        fs_rows = (
            await db.execute(
                select(FolderSet.folder_id, SetModel.id, SetModel.title)
                .join(SetModel, SetModel.id == FolderSet.set_id)
                .where(FolderSet.folder_id.in_(folder_ids), SetModel.deleted_at.is_(None))
            )
        ).all()
    sets_by_folder: dict[str, list[dict]] = {}
    for f_id, s_id, s_title in fs_rows:
        sets_by_folder.setdefault(f_id, []).append({"id": s_id, "title": s_title})

    folders_out = [
        {
            "id": f.id,
            "name": f.name,
            "created_by_admin": f.created_by_admin,
            "created_at": f.created_at,
            "set_count": len(sets_by_folder.get(f.id, [])),
            "sets": sets_by_folder.get(f.id, []),
        }
        for f in folders_rows
    ]

    # 2. Sets in user's library or owned by user or permitted
    lib_set_ids = (
        await db.execute(
            select(LibraryEntry.set_id).where(LibraryEntry.user_id == target.id)
        )
    ).scalars().all()
    perm_set_ids = (
        await db.execute(
            select(SetPermission.set_id).where(
                SetPermission.user_id == target.id,
                SetPermission.revoked_at.is_(None),
            )
        )
    ).scalars().all()
    user_visible_ids = set(lib_set_ids).union(perm_set_ids)

    assigned_sets = []
    if user_visible_ids:
        st_rows = (
            await db.execute(
                select(SetModel, User.username, User.role.label("owner_role"))
                .join(User, User.id == SetModel.owner_id)
                .where(SetModel.id.in_(user_visible_ids), SetModel.deleted_at.is_(None))
                .order_by(SetModel.title)
            )
        ).all()
        for st, owner_username, owner_role in st_rows:
            assigned_sets.append({
                "id": st.id,
                "title": st.title,
                "owner_username": owner_username,
                "is_own": st.owner_id == target.id,
                "is_admin_created": owner_role == "admin",
            })

    # 3. Available admin sets (all sets created by admins)
    admin_users = (
        await db.execute(select(User.id).where(User.role == "admin"))
    ).scalars().all()
    admin_sets_rows = (
        await db.execute(
            select(SetModel.id, SetModel.title)
            .where(SetModel.owner_id.in_(admin_users), SetModel.deleted_at.is_(None))
            .order_by(SetModel.title)
        )
    ).all()
    available_admin_sets = [
        {
            "id": s_id,
            "title": s_title,
            "is_assigned": s_id in user_visible_ids,
        }
        for s_id, s_title in admin_sets_rows
    ]

    # 4. Available admin folders
    admin_folders_rows = (
        await db.execute(
            select(Folder)
            .where(Folder.user_id.in_(admin_users))
            .order_by(Folder.name)
        )
    ).scalars().all()

    admin_f_ids = [f.id for f in admin_folders_rows]
    admin_fs_rows = []
    if admin_f_ids:
        admin_fs_rows = (
            await db.execute(
                select(FolderSet.folder_id, SetModel.id, SetModel.title)
                .join(SetModel, SetModel.id == FolderSet.set_id)
                .where(FolderSet.folder_id.in_(admin_f_ids), SetModel.deleted_at.is_(None))
            )
        ).all()
    admin_sets_by_f: dict[str, list[dict]] = {}
    for f_id, s_id, s_title in admin_fs_rows:
        admin_sets_by_f.setdefault(f_id, []).append({"id": s_id, "title": s_title})

    user_admin_folder_names = {f.name for f in folders_rows if f.created_by_admin}
    available_admin_folders = [
        {
            "id": f.id,
            "name": f.name,
            "set_count": len(admin_sets_by_f.get(f.id, [])),
            "sets": admin_sets_by_f.get(f.id, []),
            "is_assigned": f.name in user_admin_folder_names,
        }
        for f in admin_folders_rows
    ]

    return {
        "user": {"id": target.id, "username": target.username, "role": target.role},
        "folders": folders_out,
        "assigned_sets": assigned_sets,
        "available_admin_sets": available_admin_sets,
        "available_admin_folders": available_admin_folders,
    }


@router.post("/users/{user_id}/sets")
async def admin_assign_set(
    user_id: str,
    payload: AdminAssignSetIn,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    target = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if target is None:
        raise ApiError(404, "NOT_FOUND", "Пользователь не найден.")
    st = (await db.execute(select(SetModel).where(SetModel.id == payload.set_id, SetModel.deleted_at.is_(None)))).scalar_one_or_none()
    if st is None:
        raise ApiError(404, "NOT_FOUND", "Набор не найден.")

    # Add to LibraryEntry if not exists
    entry = (
        await db.execute(select(LibraryEntry).where(LibraryEntry.user_id == target.id, LibraryEntry.set_id == st.id))
    ).scalar_one_or_none()
    if entry is None:
        db.add(LibraryEntry(user_id=target.id, set_id=st.id))

    # Add to SetPermission if not exists or un-revoke
    perm = (
        await db.execute(
            select(SetPermission).where(
                SetPermission.user_id == target.id,
                SetPermission.set_id == st.id,
                SetPermission.source == "admin",
            )
        )
    ).scalar_one_or_none()
    if perm is None:
        db.add(SetPermission(user_id=target.id, set_id=st.id, permission="reader", source="admin"))
    else:
        perm.revoked_at = None

    db.add(AuditEvent(actor_id=admin.id, action="admin_assigned_set", target_type="user", target_id=target.id, details_json=json.dumps({"set_id": st.id})))
    await db.commit()
    return {"ok": True}


@router.delete("/users/{user_id}/sets/{set_id}")
async def admin_unassign_set(
    user_id: str,
    set_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    target = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if target is None:
        raise ApiError(404, "NOT_FOUND", "Пользователь не найден.")

    # Remove LibraryEntry
    await db.execute(delete(LibraryEntry).where(LibraryEntry.user_id == target.id, LibraryEntry.set_id == set_id))

    # Revoke or delete SetPermission
    await db.execute(delete(SetPermission).where(SetPermission.user_id == target.id, SetPermission.set_id == set_id))

    # Remove from user's folders
    user_folder_ids = (await db.execute(select(Folder.id).where(Folder.user_id == target.id))).scalars().all()
    if user_folder_ids:
        await db.execute(delete(FolderSet).where(FolderSet.folder_id.in_(user_folder_ids), FolderSet.set_id == set_id))

    db.add(AuditEvent(actor_id=admin.id, action="admin_unassigned_set", target_type="user", target_id=target.id, details_json=json.dumps({"set_id": set_id})))
    await db.commit()
    return {"ok": True}


@router.post("/users/{user_id}/folders")
async def admin_create_folder(
    user_id: str,
    payload: AdminFolderCreateIn,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    target = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if target is None:
        raise ApiError(404, "NOT_FOUND", "Пользователь не найден.")
    name = payload.name.strip()
    exists = (
        await db.execute(select(Folder).where(Folder.user_id == target.id, Folder.name == name))
    ).scalar_one_or_none()
    if exists:
        raise ApiError(409, "FOLDER_EXISTS", "Папка с таким названием уже есть у пользователя.")

    folder = Folder(user_id=target.id, name=name, created_by_admin=True)
    db.add(folder)
    await db.flush()

    for s_id in payload.set_ids:
        entry = (await db.execute(select(LibraryEntry).where(LibraryEntry.user_id == target.id, LibraryEntry.set_id == s_id))).scalar_one_or_none()
        if entry is None:
            db.add(LibraryEntry(user_id=target.id, set_id=s_id))
        perm = (await db.execute(select(SetPermission).where(SetPermission.user_id == target.id, SetPermission.set_id == s_id))).scalar_one_or_none()
        if perm is None:
            db.add(SetPermission(user_id=target.id, set_id=s_id, permission="reader", source="admin"))
        db.add(FolderSet(folder_id=folder.id, set_id=s_id))

    db.add(AuditEvent(actor_id=admin.id, action="admin_created_folder", target_type="user", target_id=target.id, details_json=json.dumps({"folder_name": name})))
    await db.commit()
    return {"ok": True, "folder_id": folder.id}


@router.delete("/users/{user_id}/folders/{folder_id}")
async def admin_delete_folder(
    user_id: str,
    folder_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    folder = (
        await db.execute(select(Folder).where(Folder.id == folder_id, Folder.user_id == user_id))
    ).scalar_one_or_none()
    if folder is None:
        raise ApiError(404, "NOT_FOUND", "Папка не найдена.")
    await db.execute(delete(FolderSet).where(FolderSet.folder_id == folder.id))
    await db.delete(folder)
    db.add(AuditEvent(actor_id=admin.id, action="admin_deleted_folder", target_type="folder", target_id=folder_id))
    await db.commit()
    return {"ok": True}


@router.put("/users/{user_id}/folders/{folder_id}/sets/{set_id}")
async def admin_add_set_to_folder(
    user_id: str,
    folder_id: str,
    set_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    folder = (
        await db.execute(select(Folder).where(Folder.id == folder_id, Folder.user_id == user_id))
    ).scalar_one_or_none()
    if folder is None:
        raise ApiError(404, "NOT_FOUND", "Папка не найдена.")
    st = (await db.execute(select(SetModel).where(SetModel.id == set_id, SetModel.deleted_at.is_(None)))).scalar_one_or_none()
    if st is None:
        raise ApiError(404, "NOT_FOUND", "Набор не найден.")

    entry = (await db.execute(select(LibraryEntry).where(LibraryEntry.user_id == user_id, LibraryEntry.set_id == set_id))).scalar_one_or_none()
    if entry is None:
        db.add(LibraryEntry(user_id=user_id, set_id=set_id))
    perm = (await db.execute(select(SetPermission).where(SetPermission.user_id == user_id, SetPermission.set_id == set_id))).scalar_one_or_none()
    if perm is None:
        db.add(SetPermission(user_id=user_id, set_id=set_id, permission="reader", source="admin"))

    exists = (
        await db.execute(select(FolderSet).where(FolderSet.folder_id == folder.id, FolderSet.set_id == set_id))
    ).scalar_one_or_none()
    if exists is None:
        db.add(FolderSet(folder_id=folder.id, set_id=set_id))
    await db.commit()
    return {"ok": True}


@router.delete("/users/{user_id}/folders/{folder_id}/sets/{set_id}")
async def admin_remove_set_from_folder(
    user_id: str,
    folder_id: str,
    set_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    folder = (
        await db.execute(select(Folder).where(Folder.id == folder_id, Folder.user_id == user_id))
    ).scalar_one_or_none()
    if folder is None:
        raise ApiError(404, "NOT_FOUND", "Папка не найдена.")
    await db.execute(delete(FolderSet).where(FolderSet.folder_id == folder.id, FolderSet.set_id == set_id))
    await db.commit()
    return {"ok": True}


class AdminAssignFolderIn(BaseModel):
    admin_folder_id: str


class FolderAssignmentsIn(BaseModel):
    user_ids: list[str] = Field(default_factory=list)


async def _assign_admin_folder_to_user(
    db: AsyncSession, admin_user_id: str, admin_folder_id: str, target_user_id: str
) -> tuple[str, int]:
    admin_folder = (
        await db.execute(select(Folder).where(Folder.id == admin_folder_id))
    ).scalar_one_or_none()
    if admin_folder is None:
        raise ApiError(404, "NOT_FOUND", "Папка администратора не найдена.")

    target = (await db.execute(select(User).where(User.id == target_user_id))).scalar_one_or_none()
    if target is None:
        raise ApiError(404, "NOT_FOUND", "Пользователь не найден.")

    admin_set_ids = (
        await db.execute(select(FolderSet.set_id).where(FolderSet.folder_id == admin_folder.id))
    ).scalars().all()

    user_folder = (
        await db.execute(
            select(Folder).where(Folder.user_id == target.id, Folder.name == admin_folder.name)
        )
    ).scalar_one_or_none()
    if user_folder is None:
        user_folder = Folder(user_id=target.id, name=admin_folder.name, created_by_admin=True)
        db.add(user_folder)
        await db.flush()
    else:
        user_folder.created_by_admin = True

    for s_id in admin_set_ids:
        entry = (
            await db.execute(
                select(LibraryEntry).where(LibraryEntry.user_id == target.id, LibraryEntry.set_id == s_id)
            )
        ).scalar_one_or_none()
        if entry is None:
            db.add(LibraryEntry(user_id=target.id, set_id=s_id))

        perm = (
            await db.execute(
                select(SetPermission).where(
                    SetPermission.user_id == target.id,
                    SetPermission.set_id == s_id,
                    SetPermission.source == "admin",
                )
            )
        ).scalar_one_or_none()
        if perm is None:
            db.add(SetPermission(user_id=target.id, set_id=s_id, permission="reader", source="admin"))
        else:
            perm.revoked_at = None

        fs = (
            await db.execute(
                select(FolderSet).where(
                    FolderSet.folder_id == user_folder.id,
                    FolderSet.set_id == s_id,
                )
            )
        ).scalar_one_or_none()
        if fs is None:
            db.add(FolderSet(folder_id=user_folder.id, set_id=s_id))

    current_fs = (
        await db.execute(select(FolderSet.set_id).where(FolderSet.folder_id == user_folder.id))
    ).scalars().all()
    stale_fs = set(current_fs) - set(admin_set_ids)
    if stale_fs:
        await db.execute(
            delete(FolderSet).where(
                FolderSet.folder_id == user_folder.id,
                FolderSet.set_id.in_(stale_fs),
            )
        )

    db.add(
        AuditEvent(
            actor_id=admin_user_id,
            action="admin_assigned_folder",
            target_type="user",
            target_id=target.id,
            details_json=json.dumps({"folder_name": admin_folder.name, "admin_folder_id": admin_folder.id}),
        )
    )
    await db.commit()
    return user_folder.id, len(admin_set_ids)


async def _unassign_admin_folder_from_user(
    db: AsyncSession, admin_user_id: str, admin_folder_id: str, target_user_id: str
) -> None:
    admin_folder = (
        await db.execute(select(Folder).where(Folder.id == admin_folder_id))
    ).scalar_one_or_none()
    if admin_folder is None:
        return

    user_folder = (
        await db.execute(
            select(Folder).where(
                Folder.user_id == target_user_id,
                Folder.name == admin_folder.name,
                Folder.created_by_admin.is_(True),
            )
        )
    ).scalar_one_or_none()
    if user_folder:
        await db.execute(delete(FolderSet).where(FolderSet.folder_id == user_folder.id))
        await db.delete(user_folder)
        db.add(
            AuditEvent(
                actor_id=admin_user_id,
                action="admin_unassigned_folder",
                target_type="user",
                target_id=target_user_id,
                details_json=json.dumps({"folder_name": admin_folder.name}),
            )
        )
        await db.commit()


@router.post("/users/{user_id}/folders/assign")
async def admin_assign_folder_to_user(
    user_id: str,
    payload: AdminAssignFolderIn,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    folder_id, set_count = await _assign_admin_folder_to_user(
        db, admin.id, payload.admin_folder_id, user_id
    )
    return {"ok": True, "folder_id": folder_id, "set_count": set_count}


@router.get("/folders/{folder_id}/assignments")
async def get_folder_assignments(
    folder_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    folder = (
        await db.execute(select(Folder).where(Folder.id == folder_id))
    ).scalar_one_or_none()
    if folder is None:
        raise ApiError(404, "NOT_FOUND", "Папка не найдена.")

    set_count = (
        await db.execute(
            select(func.count()).select_from(FolderSet).where(FolderSet.folder_id == folder.id)
        )
    ).scalar_one()

    users = (
        await db.execute(
            select(User.id, User.username)
            .where(User.role != "admin", User.is_active.is_(True))
            .order_by(User.username)
        )
    ).all()

    assigned_user_ids = set(
        (
            await db.execute(
                select(Folder.user_id).where(
                    Folder.name == folder.name,
                    Folder.created_by_admin.is_(True),
                )
            )
        ).scalars().all()
    )

    return {
        "folder": {"id": folder.id, "name": folder.name, "set_count": set_count},
        "users": [
            {
                "id": u_id,
                "username": u_name,
                "is_assigned": u_id in assigned_user_ids,
            }
            for u_id, u_name in users
        ],
    }


@router.post("/folders/{folder_id}/assignments")
async def update_folder_assignments(
    folder_id: str,
    payload: FolderAssignmentsIn,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    folder = (
        await db.execute(select(Folder).where(Folder.id == folder_id))
    ).scalar_one_or_none()
    if folder is None:
        raise ApiError(404, "NOT_FOUND", "Папка не найдена.")

    target_ids = set(payload.user_ids)

    current_assigned = set(
        (
            await db.execute(
                select(Folder.user_id).where(
                    Folder.name == folder.name,
                    Folder.created_by_admin.is_(True),
                )
            )
        ).scalars().all()
    )

    to_remove = current_assigned - target_ids

    for u_id in target_ids:
        await _assign_admin_folder_to_user(db, admin.id, folder.id, u_id)

    for u_id in to_remove:
        await _unassign_admin_folder_from_user(db, admin.id, folder.id, u_id)

    return {"ok": True, "assigned_count": len(target_ids)}

