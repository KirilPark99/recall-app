"""Модели: занятия, ответы, SRS-состояния, статистика."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UuidPk, UTCDateTime, UTCDateTime, utcnow


class StudySession(Base, UuidPk):
    __tablename__ = "study_sessions"
    __table_args__ = (Index("ix_study_sessions_user_status", "user_id", "status", "last_activity_at"),)

    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)  # cards|learn|write|spell|test|match|srs
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)  # active|paused|completed|abandoned|voided
    settings_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)  # неизменяемый снимок настроек
    sources_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    state_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)  # рабочее состояние (learn-очередь и т.п.)
    pool_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)  # снимок выбранных карточек
    current_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    active_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # оценка активного времени
    deadline_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)  # таймер теста
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    last_activity_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    items: Mapped[list["StudySessionItem"]] = relationship(back_populates="session", order_by="StudySessionItem.position")


class StudySessionItem(Base, UuidPk):
    __tablename__ = "study_session_items"
    __table_args__ = (
        UniqueConstraint("session_id", "item_uid", name="uq_session_item_uid"),
        Index("ix_items_session_pos", "session_id", "position"),
    )

    session_id: Mapped[str] = mapped_column(String(32), ForeignKey("study_sessions.id", ondelete="CASCADE"), nullable=False)
    item_uid: Mapped[str] = mapped_column(String(32), nullable=False)  # стабильный клиентский ID задания
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    card_id: Mapped[str] = mapped_column(String(32), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)  # front_to_back|back_to_front
    content_version: Mapped[int] = mapped_column(Integer, nullable=False)
    task_type: Mapped[str] = mapped_column(String(24), nullable=False)
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)  # публичная часть (тексты, медиа, контекст)
    choices_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # варианты MC (без пометки верного)
    answer_key_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # ключ ответа, только сервер
    draft_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    draft_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)  # pending|answered|skipped
    skipped: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    revealed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)

    session: Mapped[StudySession] = relationship(back_populates="items")


class StudyAnswer(Base, UuidPk):
    __tablename__ = "study_answers"
    __table_args__ = (
        UniqueConstraint("user_id", "client_event_id", name="uq_answer_client_event"),
        UniqueConstraint("session_id", "item_id", "attempt_no", name="uq_answer_attempt"),
        Index("ix_study_answers_session", "session_id"),
    )

    session_id: Mapped[str] = mapped_column(String(32), ForeignKey("study_sessions.id", ondelete="CASCADE"), nullable=False)
    item_id: Mapped[str] = mapped_column(String(32), ForeignKey("study_session_items.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    client_event_id: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalized_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    machine_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    final_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    assisted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    answer_type: Mapped[str] = mapped_column(String(24), nullable=False)  # auto|self_assess|manual_correction|match_move|skip
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fingerprint: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    correction_of_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("study_answers.id", ondelete="SET NULL"), nullable=True)
    answered_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)


class TestAttempt(Base, UuidPk):
    __tablename__ = "test_attempts"
    __table_args__ = (UniqueConstraint("session_id", name="uq_test_attempt_session"),)

    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(String(32), ForeignKey("study_sessions.id", ondelete="CASCADE"), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    max_score: Mapped[int] = mapped_column(Integer, nullable=False)
    adjusted_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detail_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    finished_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)


class MatchRecord(Base, UuidPk):
    __tablename__ = "match_records"

    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    board_size: Mapped[int] = mapped_column(Integer, nullable=False)
    penalty_rule: Mapped[str] = mapped_column(String(32), nullable=False)
    elapsed_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    mistakes: Mapped[int] = mapped_column(Integer, nullable=False)
    penalty_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    final_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)


class SrsState(Base, TimestampMixin, UuidPk):
    __tablename__ = "srs_states"
    __table_args__ = (
        UniqueConstraint("user_id", "card_id", "direction", name="uq_srs_state"),
        Index("ix_srs_states_queue", "user_id", "suspended", "due_at"),
    )

    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    card_id: Mapped[str] = mapped_column(String(32), ForeignKey("cards.id", ondelete="CASCADE"), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    algorithm_name: Mapped[str] = mapped_column(String(32), default="fsrs", nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)
    scheduler_payload: Mapped[str] = mapped_column(Text, nullable=False)  # полный сериализуемый payload
    due_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    last_review_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    state_name: Mapped[str] = mapped_column(String(16), nullable=False)  # learning|review|relearning
    suspended: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_reviewed_content_version: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    learning_epoch: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class SrsReview(Base, UuidPk):
    __tablename__ = "srs_reviews"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_srs_review_idem"),
        Index("ix_srs_reviews_user_time", "user_id", "reviewed_at"),
    )

    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    card_id: Mapped[str] = mapped_column(String(32), ForeignKey("cards.id", ondelete="CASCADE"), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    srs_state_id: Mapped[str] = mapped_column(String(32), ForeignKey("srs_states.id", ondelete="CASCADE"), nullable=False)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    before_payload: Mapped[str] = mapped_column(Text, nullable=False)
    after_payload: Mapped[str] = mapped_column(Text, nullable=False)
    before_due_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    after_due_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    before_state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    after_state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    card_content_version: Mapped[int] = mapped_column(Integer, nullable=False)
    study_session_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("study_sessions.id", ondelete="SET NULL"), nullable=True)
    reviewed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    undone_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    is_undo_event: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    learning_epoch: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class DailyGoal(Base, UuidPk):
    __tablename__ = "daily_goals"
    __table_args__ = (UniqueConstraint("user_id", "local_date", name="uq_daily_goal"),)

    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    local_date: Mapped[str] = mapped_column(String(10), nullable=False)  # YYYY-MM-DD
    timezone_at_creation: Mapped[str] = mapped_column(String(64), nullable=False)
    target_reviews: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    target_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    target_new_cards: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False)


class ActivityEvent(Base, UuidPk):
    __tablename__ = "activity_events"
    __table_args__ = (
        Index("ix_activity_user_time", "user_id", "occurred_at_utc"),
        Index("ix_activity_user_date", "user_id", "local_date"),
    )

    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    occurred_at_utc: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    local_date: Mapped[str] = mapped_column(String(10), nullable=False)
    set_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    card_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    meta_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)


class SearchIndex(Base):
    """FTS5-таблица создаётся миграцией при доступности FTS5; эта модель используется
    только для fallback-пути (нормализованный текст)."""
    __tablename__ = "search_fallback"
    __table_args__ = (UniqueConstraint("set_id", name="uq_search_fallback_set"),)

    set_id: Mapped[str] = mapped_column(String(32), ForeignKey("sets.id", ondelete="CASCADE"), primary_key=True)
    normalized_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
