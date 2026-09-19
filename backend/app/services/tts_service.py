"""TTS сервис на основе Edge TTS (нейросетевые голоса студийного качества)."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

import edge_tts

from app.core.config import settings

logger = logging.getLogger(__name__)

# Таблица качественных естественных нейроголосов (Female, Male) по языкам
NEURAL_VOICES: dict[str, dict[str, str]] = {
    "ru": {
        "female": "ru-RU-SvetlanaNeural",
        "male": "ru-RU-DmitryNeural",
    },
    "en": {
        "female": "en-US-AvaNeural",
        "male": "en-US-AndrewNeural",
    },
    "de": {
        "female": "de-DE-KatjaNeural",
        "male": "de-DE-FlorianMultilingualNeural",
    },
    "fr": {
        "female": "fr-FR-DeniseNeural",
        "male": "fr-FR-HenriNeural",
    },
    "es": {
        "female": "es-ES-ElviraNeural",
        "male": "es-ES-AlvaroNeural",
    },
    "it": {
        "female": "it-IT-ElsaNeural",
        "male": "it-IT-DiegoNeural",
    },
    "zh": {
        "female": "zh-CN-XiaoxiaoNeural",
        "male": "zh-CN-YunxiNeural",
    },
    "ja": {
        "female": "ja-JP-NanamiNeural",
        "male": "ja-JP-KeitaNeural",
    },
    "ko": {
        "female": "ko-KR-SunHiNeural",
        "male": "ko-KR-InJoonNeural",
    },
    "tr": {
        "female": "tr-TR-EmelNeural",
        "male": "tr-TR-AhmetNeural",
    },
    "pl": {
        "female": "pl-PL-ZofiaNeural",
        "male": "pl-PL-MarekNeural",
    },
    "uk": {
        "female": "uk-UA-PolinaNeural",
        "male": "uk-UA-OstapNeural",
    },
    "pt": {
        "female": "pt-BR-FranciscaNeural",
        "male": "pt-BR-AntonioNeural",
    },
    "ar": {
        "female": "ar-SA-ZariyahNeural",
        "male": "ar-SA-HamedNeural",
    },
    "nl": {
        "female": "nl-NL-ColetteNeural",
        "male": "nl-NL-FennaNeural",
    },
    "sv": {
        "female": "sv-SE-SofieNeural",
        "male": "sv-SE-MattiasNeural",
    },
}

_CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")
_locks: dict[str, asyncio.Lock] = {}
_global_lock = asyncio.Lock()


def cleanup_tts_cache(max_bytes: int | None = None, ttl_days: int | None = None) -> int:
    """Delete expired files, then oldest files until the configured cache cap."""
    cache_dir = settings.tts_cache_dir
    if not cache_dir.exists():
        return 0
    max_bytes = settings.tts_cache_max_bytes if max_bytes is None else max_bytes
    ttl_days = settings.tts_cache_ttl_days if ttl_days is None else ttl_days
    cutoff = time.time() - ttl_days * 86400
    files = [p for p in cache_dir.glob("*.mp3") if p.is_file()]
    removed = 0
    for path in files:
        if path.stat().st_mtime < cutoff:
            path.unlink(missing_ok=True)
            removed += 1
    files = sorted((p for p in files if p.exists()), key=lambda p: p.stat().st_mtime)
    total = sum(p.stat().st_size for p in files)
    for path in files:
        if total <= max_bytes:
            break
        total -= path.stat().st_size
        path.unlink(missing_ok=True)
        removed += 1
    return removed


def resolve_voice(
    text: str,
    lang: str | None = None,
    gender: str = "female",
    requested_voice: str | None = None,
) -> str:
    """Определяет наилучший естественный нейроголос для текста."""
    if requested_voice and requested_voice.strip():
        return requested_voice.strip()

    normalized_lang = (lang or "").strip().lower()
    short_lang = normalized_lang.split("-")[0].split("_")[0] if normalized_lang else ""

    has_cyrillic = bool(_CYRILLIC_RE.search(text))

    # Если в тексте есть кириллица, а язык не кириллический — используем ru
    if has_cyrillic and short_lang not in ("ru", "uk", "be", "bg"):
        short_lang = "ru"
    elif not has_cyrillic and short_lang in ("ru", "uk", "be", "bg"):
        # Если в тексте латиница, а язык был ru — переключаем на en
        short_lang = "en"
    elif not short_lang or short_lang == "auto":
        short_lang = "ru" if has_cyrillic else "en"

    g = "male" if gender.lower() == "male" else "female"
    lang_voices = NEURAL_VOICES.get(short_lang)
    if lang_voices:
        return lang_voices.get(g, lang_voices["female"])

    # Fallback на английский
    return NEURAL_VOICES["en"][g]


def format_rate(rate: float) -> str:
    """Форматирует скорость речи в строку для Edge TTS (например, +0%, +25%, -15%)."""
    clamped = max(0.5, min(2.0, rate))
    pct = int(round((clamped - 1.0) * 100))
    return f"{pct:+d}%"


async def synthesize_speech(
    text: str,
    lang: str | None = None,
    rate: float = 1.0,
    voice: str | None = None,
    gender: str = "female",
) -> Path:
    """Синтезирует речь с кэшированием на диск. Возвращает путь к MP3-файлу."""
    clean_text = text.strip()
    if not clean_text:
        raise ValueError("Текст для озвучки не может быть пустым.")
    if len(clean_text) > 2000:
        clean_text = clean_text[:2000]

    selected_voice = resolve_voice(clean_text, lang, gender, voice)
    rate_str = format_rate(rate)

    cache_key = hashlib.sha256(
        f"{selected_voice}:{rate_str}:{clean_text}".encode("utf-8")
    ).hexdigest()

    cache_dir = settings.tts_cache_dir
    cache_dir.mkdir(parents=True, exist_ok=True)
    cleanup_tts_cache()
    cache_file = cache_dir / f"{cache_key}.mp3"

    if cache_file.is_file() and cache_file.stat().st_size > 0:
        return cache_file

    async with _global_lock:
        if cache_key not in _locks:
            _locks[cache_key] = asyncio.Lock()
        lock = _locks[cache_key]

    try:
        async with lock:
            # Проверяем ещё раз внутри блокировки
            if cache_file.is_file() and cache_file.stat().st_size > 0:
                return cache_file

            tmp_file = cache_dir / f"{cache_key}.tmp.{os.getpid()}"
            comm = edge_tts.Communicate(clean_text, selected_voice, rate=rate_str)
            with open(tmp_file, "wb") as f:
                async for chunk in comm.stream():
                    if chunk["type"] == "audio":
                        f.write(chunk["data"])

            if not tmp_file.is_file() or tmp_file.stat().st_size == 0:
                raise RuntimeError("Edge TTS не вернул аудиоданные.")

            tmp_file.replace(cache_file)
            logger.info(
                "Синтезирована речь: голос=%s, размер=%d байт, текст=%r",
                selected_voice,
                cache_file.stat().st_size,
                clean_text[:40],
            )
            return cache_file
    finally:
        tmp_file = cache_dir / f"{cache_key}.tmp.{os.getpid()}"
        if tmp_file.is_file():
            try:
                tmp_file.unlink(missing_ok=True)
            except Exception:
                pass
        async with _global_lock:
            if not lock.locked():
                _locks.pop(cache_key, None)


def get_available_voices() -> list[dict[str, Any]]:
    """Возвращает список поддерживаемых нейросетевых голосов."""
    result = []
    for lang, genders in NEURAL_VOICES.items():
        for gender, voice_name in genders.items():
            result.append(
                {
                    "language": lang,
                    "gender": gender,
                    "voice": voice_name,
                }
            )
    return result
