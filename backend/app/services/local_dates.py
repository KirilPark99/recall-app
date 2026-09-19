"""Локальные календарные даты пользователя (IANA timezone), UTC-хранение."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import settings


def safe_zone(timezone_name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name or settings.default_timezone)
    except (ZoneInfoNotFoundError, KeyError, ValueError):
        return ZoneInfo(settings.default_timezone)


def local_date_for(user_tz: str | None, at_utc: datetime | None = None) -> str:
    now = at_utc or datetime.now(timezone.utc).replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(safe_zone(user_tz)).strftime("%Y-%m-%d")


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
