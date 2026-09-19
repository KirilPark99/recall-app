"""Медиа endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import client_ip, get_current_user, get_db
from app.core.ratelimit import check_rate_limit
from app.core.config import settings
from app.models import User
from app.services.media_service import delete_media, media_accessible, save_upload

router = APIRouter(prefix="/media", tags=["media"])


@router.post("/upload", status_code=201)
async def upload(
    request: Request,
    file: UploadFile = File(...),
    description: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    check_rate_limit(f"media-upload:{user.id}:{client_ip(request)}", 30, 60)
    media = await save_upload(db, user, file, description)
    return {
        "id": media.id,
        "media_type": media.media_type,
        "mime_type": media.mime_type,
        "original_name": media.original_name,
        "byte_size": media.byte_size,
        "width": media.width,
        "height": media.height,
        "duration_ms": media.duration_ms,
        "description": media.description,
        "url": f"/api/v1/media/{media.id}",
    }


@router.get("/{media_id}")
async def download(
    media_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    media = await media_accessible(db, user, media_id)
    path = settings.media_dir / media.storage_key
    if not path.is_file():
        from app.core.errors import ApiError

        raise ApiError(404, "NOT_FOUND", "Файл не найден.")
    return FileResponse(
        path,
        media_type=media.mime_type,
        headers={
            "Content-Disposition": f'inline; filename="{media.id}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, max-age=86400",
        },
    )


@router.delete("/{media_id}")
async def remove(
    media_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    await delete_media(db, user, media_id)
    return {"ok": True}
