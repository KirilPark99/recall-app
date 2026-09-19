"""API эндпоинты для высококачественного нейросетевого TTS."""
from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import FileResponse

from app.core.errors import ApiError
from app.api.deps import client_ip, get_current_user
from app.core.ratelimit import check_rate_limit
from app.models import User
from app.services.tts_service import (
    get_available_voices,
    synthesize_speech,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tts", tags=["tts"])


@router.get("")
async def text_to_speech(
    request: Request,
    text: str = Query(..., min_length=1, max_length=2000, description="Текст для озвучки"),
    lang: str | None = Query(default=None, description="Языковой код (ru, en, de, fr и т.д.)"),
    rate: float = Query(default=1.0, ge=0.5, le=2.0, description="Скорость речи (0.5 - 2.0)"),
    voice: str | None = Query(default=None, description="Имя конкретного нейроголоса"),
    gender: str = Query(default="female", description="Пол голоса (female / male)"),
    user: User = Depends(get_current_user),
) -> Response:
    """Генерирует естественное человеческое произношение текста студийного качества."""
    check_rate_limit(f"tts:{user.id}:{client_ip(request)}", 30, 60)
    try:
        audio_path = await synthesize_speech(
            text=text,
            lang=lang,
            rate=rate,
            voice=voice,
            gender=gender,
        )
    except Exception as e:
        logger.exception("Ошибка генерации речи через Edge TTS")
        raise ApiError(500, "TTS_SYNTHESIS_FAILED", "Не удалось синтезировать речь.") from e

    return FileResponse(
        path=audio_path,
        media_type="audio/mpeg",
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "Accept-Ranges": "bytes",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/voices")
async def list_tts_voices(user: User = Depends(get_current_user)) -> dict:
    """Возвращает список доступных нейросетевых голосов."""
    return {"voices": get_available_voices()}
