"""Модели: личные данные пользователя (настройки, библиотека, SRS-подписки)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UuidPk, UTCDateTime, UTCDateTime, utcnow


class UserPreferences(Base, TimestampMixin):
    __tablename__ = "user_preferences"

    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    daily_goal_reviews: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    daily_goal_minutes: Mapped[int] = mapped_column(Integer, default=15, nullable=False)
    daily_goal_new_cards: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    batch_size: Mapped[int] = mapped_column(Integer, default=7, server_default="7", nullable=False)
    goals_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    streak_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sound_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    autoplay_audio: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    volume: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    tts_rate: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    prefer_local_voices: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    allow_network_voices: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    default_direction: Mapped[str] = mapped_column(String(16), default="front_to_back", nullable=False)
    normalization_policy: Mapped[str] = mapped_column(String(16), default="default", nullable=False)  # default|strict|lenient
    font_scale: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    reduced_motion: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class LibraryEntry(Base, TimestampMixin, UuidPk):
    __tablename__ = "library_entries"
    __table_args__ = (UniqueConstraint("user_id", "set_id", name="uq_library_user_set"),)

    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    set_id: Mapped[str] = mapped_column(String(32), ForeignKey("sets.id", ondelete="CASCADE"), nullable=False)
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    saved_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    last_studied_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class UserCardFlag(Base, UuidPk):
    __tablename__ = "user_card_flags"
    __table_args__ = (UniqueConstraint("user_id", "card_id", name="uq_card_flag"),)

    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    card_id: Mapped[str] = mapped_column(String(32), ForeignKey("cards.id", ondelete="CASCADE"), nullable=False)
    is_starred: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False)


class SrsEnrollment(Base, TimestampMixin, UuidPk):
    __tablename__ = "srs_enrollments"
    __table_args__ = (UniqueConstraint("user_id", "set_id", name="uq_srs_enrollment"),)

    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    set_id: Mapped[str] = mapped_column(String(32), ForeignKey("sets.id", ondelete="CASCADE"), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    forward_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    reverse_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class SrsSettings(Base, TimestampMixin):
    __tablename__ = "srs_settings"

    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    desired_retention: Mapped[float] = mapped_column(Float, default=0.9, nullable=False)
    new_per_day: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    round_size: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    config_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    params_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
