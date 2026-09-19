"""Общая база моделей."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.sqlite import DATETIME as SQLITE_DATETIME
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


def utcnow() -> datetime:
    # TZ-aware UTC: в SQLite храним наивные строки UTC (см. UTCDateTime),
    # в Python сравниваем и сериализуем с явным смещением.
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """DateTime: хранит naive-UTC строки SQLite, отдаёт всегда aware-UTC —
    JSON-сериализация содержит "+00:00", браузер парсит корректно."""

    impl = SQLITE_DATETIME
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


def new_uuid() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False
    )


class UuidPk:
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_uuid)
