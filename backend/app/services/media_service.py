"""Медиа: безопасная загрузка, хранение вне статики, выдача с проверкой доступа."""
from __future__ import annotations

import hashlib
import io
import os

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import ApiError
from app.db.base import new_uuid, utcnow
from app.models import CardMedia, Media, SnapshotMedia, User

IMAGE_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}
AUDIO_MAGICS = (
    (b"ID3", "audio/mpeg", "mp3"),
    (b"RIFF", "audio/wav", "wav"),
    (b"OggS", "audio/ogg", "ogg"),
)


def _sniff_image(data: bytes) -> str | None:
    from PIL import Image

    try:
        img = Image.open(io.BytesIO(data))
        img.verify()
        img = Image.open(io.BytesIO(data))
        fmt = (img.format or "").upper()
        w, h = img.size
        if w * h > 20_000_000:
            raise ApiError(413, "IMAGE_TOO_LARGE", "Изображение больше 20 мегапикселей.")
        return {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp", "GIF": "image/gif"}.get(fmt)
    except ApiError:
        raise
    except Exception:
        return None


def _sniff_audio(data: bytes) -> str | None:
    for magic, mime, ext in AUDIO_MAGICS:
        if data[: len(magic)] == magic:
            return mime
    if len(data) > 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0:
        return "audio/mpeg"
    return None


def _wav_duration_ms(data: bytes) -> int | None:
    import wave

    try:
        with wave.open(io.BytesIO(data)) as w:
            frames = w.getnframes()
            rate = w.getframerate() or 1
            return int(frames * 1000 / rate)
    except Exception:
        return None


async def save_upload(db: AsyncSession, user: User, file: UploadFile, description: str) -> Media:
    chunks = []
    total_read = 0
    while chunk := await file.read(1024 * 1024):
        total_read += len(chunk)
        if total_read > settings.max_audio_bytes:
            raise ApiError(413, "FILE_TOO_LARGE", f"Максимальный размер файла: {settings.max_audio_bytes // (1024 * 1024)} MiB.")
        chunks.append(chunk)
    data = b"".join(chunks)
    if not data:
        raise ApiError(422, "EMPTY_FILE", "Файл пуст.")
    mime = _sniff_image(data)
    media_type = "image"
    limit = settings.max_image_bytes
    if mime is None:
        mime = _sniff_audio(data)
        media_type = "audio"
        limit = settings.max_audio_bytes
    if mime is None:
        raise ApiError(415, "UNSUPPORTED_MEDIA_TYPE", "Поддерживаются изображения PNG/JPEG/WebP/GIF и аудио MP3/WAV/OGG.")
    if len(data) > limit:
        raise ApiError(413, "FILE_TOO_LARGE", f"Максимальный размер этого типа файла: {limit // (1024 * 1024)} MiB.")

    extra = {}
    if media_type == "image":
        # Перекодирование убирает EXIF (включая GPS) и опасные метаданные.
        from PIL import Image

        img = Image.open(io.BytesIO(data))
        out = io.BytesIO()
        if mime == "image/jpeg":
            img.convert("RGB").save(out, format="JPEG", quality=90)
        elif mime == "image/png":
            img.save(out, format="PNG")
        elif mime == "image/webp":
            img.save(out, format="WEBP", quality=90)
        else:
            img.save(out, format="GIF")
        data = out.getvalue()
        extra = {"width": img.width, "height": img.height}
    elif mime == "audio/wav":
        d = _wav_duration_ms(data)
        if d:
            extra = {"duration_ms": d}

    sha = hashlib.sha256(data).hexdigest()
    ext = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif",
           "audio/mpeg": "mp3", "audio/wav": "wav", "audio/ogg": "ogg"}[mime]
    existing = (
        await db.execute(select(Media).where(Media.owner_id == user.id, Media.sha256 == sha))
    ).scalars().first()
    if existing is not None and existing.deleted_at is None:
        return existing
    storage_key = existing.storage_key if existing is not None else f"{user.id}/{sha[:2]}/{sha}.{ext}"
    # Квота на суммарный размер медиа пользователя.
    total = (
        await db.execute(
            select(func_media_sum()).where(Media.owner_id == user.id, Media.deleted_at.is_(None))
        )
    ).scalar_one() or 0
    from app.core.config import settings as s

    per_user_cap = 500 * 1024 * 1024  # 500 MiB на пользователя по умолчанию
    if total + len(data) > per_user_cap:
        raise ApiError(413, "QUOTA_EXCEEDED", "Достигнут лимит хранилища медиа. Удалите неиспользуемые файлы.")

    path = settings.media_dir / storage_key
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(data)
        os.chmod(path, 0o640)
    media = existing or Media(owner_id=user.id, storage_key=storage_key, sha256=sha)
    media.original_name = (file.filename or "file")[:255]
    media.media_type = media_type
    media.mime_type = mime
    media.byte_size = len(data)
    media.description = (description or "")[:500]
    media.deleted_at = None
    for key, value in extra.items():
        setattr(media, key, value)
    if existing is None:
        db.add(media)
    await db.commit()
    await db.refresh(media)
    return media


def func_media_sum():
    from sqlalchemy import func

    return func.coalesce(func.sum(Media.byte_size), 0)


async def media_accessible(db: AsyncSession, user: User, media_id: str) -> Media:
    media = (
        await db.execute(select(Media).where(Media.id == media_id, Media.deleted_at.is_(None)))
    ).scalar_one_or_none()
    if media is None:
        raise ApiError(404, "NOT_FOUND", "Файл не найден.")
    if media.owner_id == user.id:
        return media
    # Доступ через карточку набора, который пользователь может читать (или через снимок занятия).
    from app.models import Card
    from app.services.access import get_set_access

    row = (
        await db.execute(select(CardMedia).where(CardMedia.media_id == media.id).limit(1))
    ).scalar_one_or_none()
    if row is not None:
        card = (await db.execute(select(Card).where(Card.id == row.card_id))).scalar_one_or_none()
        if card is not None:
            await get_set_access(db, user, card.set_id)
            return media
    from app.models import StudySession

    snap = (
        await db.execute(
            select(SnapshotMedia.id)
            .join(StudySession, StudySession.id == SnapshotMedia.study_session_id)
            .where(SnapshotMedia.media_id == media.id, StudySession.user_id == user.id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if snap is not None:
        return media
    raise ApiError(404, "NOT_FOUND", "Файл не найден.")


async def delete_media(db: AsyncSession, user: User, media_id: str) -> None:
    media = (
        await db.execute(select(Media).where(Media.id == media_id, Media.deleted_at.is_(None)))
    ).scalar_one_or_none()
    if media is None or media.owner_id != user.id:
        raise ApiError(404, "NOT_FOUND", "Файл не найден.")
    refs = (
        await db.execute(select(CardMedia.id).where(CardMedia.media_id == media.id).limit(1))
    ).scalar_one_or_none()
    snaps = (
        await db.execute(select(SnapshotMedia.id).where(SnapshotMedia.media_id == media.id).limit(1))
    ).scalar_one_or_none()
    if refs is not None or snaps is not None:
        raise ApiError(409, "MEDIA_IN_USE", "Файл используется карточкой или сохранённым занятием.")
    media.deleted_at = utcnow()
    await db.commit()
    path = settings.media_dir / media.storage_key
    if path.exists():
        path.unlink()
