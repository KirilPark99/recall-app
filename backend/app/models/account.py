"""Модели: пользователи, сессии, настройки сервера."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UuidPk, UTCDateTime, UTCDateTime, utcnow


class User(Base, TimestampMixin, UuidPk):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    username_normalized: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), default="user", nullable=False)  # admin|user
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    preferred_locale: Mapped[str] = mapped_column(String(8), default="ru", nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Moscow", nullable=False)
    theme: Mapped[str] = mapped_column(String(16), default="system", nullable=False)  # light|dark|system
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    sessions: Mapped[list["Session"]] = relationship(back_populates="user", foreign_keys="Session.user_id")


class Session(Base, UuidPk):
    __tablename__ = "sessions"

    user_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # pre_auth|authenticated
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    csrf_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(300), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)

    user: Mapped[User | None] = relationship(back_populates="sessions", foreign_keys=[user_id])


class ServerSetting(Base):
    __tablename__ = "server_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False)


class AuditEvent(Base, UuidPk):
    __tablename__ = "audit_events"

    actor_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result: Mapped[str] = mapped_column(String(16), default="ok", nullable=False)
    details_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False, index=True)


class ImportJob(Base, UuidPk):
    __tablename__ = "import_jobs"

    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), default="preview", nullable=False)  # preview|ready|completed|failed|interrupted
    source_format: Mapped[str] = mapped_column(String(16), nullable=False)
    target_set_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("sets.id", ondelete="SET NULL"), nullable=True)
    create_new_set: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    new_set_title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    duplicate_policy: Mapped[str] = mapped_column(String(16), default="skip", nullable=False)  # skip|update|add
    expected_content_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    preview_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    staging_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    errors_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    applied_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
