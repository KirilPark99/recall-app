"""Служебные endpoints: health, ready, публичная конфигурация."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.config import settings
from app.core.db import migrations_ready

router = APIRouter(tags=["system"])

APP_VERSION = "1.0.0"
APP_NAME = "Recall"


@router.get("/health")
async def health():
    """Легковесная проверка: процесс жив; базу не трогает."""
    return {"status": "ok", "name": APP_NAME, "version": APP_VERSION, "env": settings.app_env}


@router.get("/ready")
async def ready(db: AsyncSession = Depends(get_db)):
    """Готовность: миграции применены, база отвечает."""
    try:
        ok = await migrations_ready()
        if not ok:
            return JSONResponse({"status": "unready", "reason": "migrations_or_integrity"}, status_code=503)
        await db.execute(text("SELECT 1"))
        return {"status": "ok", "migrations": "applied"}
    except Exception:
        return JSONResponse({"status": "unready", "reason": "database_error"}, status_code=503)


@router.get("/config/public")
async def public_config(db: AsyncSession = Depends(get_db)):
    from app.services.settings_service import get_setting

    return {
        "app_name": APP_NAME,
        "version": APP_VERSION,
        "registration_enabled": await get_setting(db, "registration_enabled", False),
        "default_locale": settings.default_locale,
        "allowed_locales": settings.allowed_locales_list,
        "default_timezone": settings.default_timezone,
        "limits": {
            "max_image_bytes": settings.max_image_bytes,
            "max_audio_bytes": settings.max_audio_bytes,
            "max_import_bytes": settings.max_import_bytes,
            "max_cards_per_set": settings.max_cards_per_set,
            "max_import_rows": settings.max_import_rows,
            "page_default_size": settings.page_default_size,
            "page_max_size": settings.page_max_size,
            "max_test_questions": settings.max_test_questions,
        },
    }
