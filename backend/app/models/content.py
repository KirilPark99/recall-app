"""Модели: наборы, карточки, теги, папки, доступ, медиа."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UuidPk, UTCDateTime, UTCDateTime, utcnow


class SetModel(Base, TimestampMixin, UuidPk):
    __tablename__ = "sets"
    __table_args__ = (
        Index("ix_sets_owner_updated", "owner_id", "updated_at"),
        Index("ix_sets_visibility_updated", "visibility", "updated_at"),
        Index("ix_sets_archived", "archived"),
    )

    owner_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    front_language: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    back_language: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    visibility: Mapped[str] = mapped_column(String(16), default="private", nullable=False)  # private|server_public|link
    archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    content_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    share_revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    cards: Mapped[list["Card"]] = relationship(back_populates="set_model", order_by="Card.position", foreign_keys="Card.set_id")


class Card(Base, TimestampMixin, UuidPk):
    __tablename__ = "cards"
    __table_args__ = (Index("ix_cards_set_position", "set_id", "position"),)

    set_id: Mapped[str] = mapped_column(String(32), ForeignKey("sets.id", ondelete="CASCADE"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    content_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    front_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    back_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    front_context: Mapped[str] = mapped_column(Text, default="", nullable=False)
    back_context: Mapped[str] = mapped_column(Text, default="", nullable=False)
    front_hint: Mapped[str] = mapped_column(Text, default="", nullable=False)
    back_hint: Mapped[str] = mapped_column(Text, default="", nullable=False)
    front_explanation: Mapped[str] = mapped_column(Text, default="", nullable=False)
    back_explanation: Mapped[str] = mapped_column(Text, default="", nullable=False)
    front_example: Mapped[str] = mapped_column(Text, default="", nullable=False)
    back_example: Mapped[str] = mapped_column(Text, default="", nullable=False)
    front_language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    back_language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    enabled_front_to_back: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    enabled_back_to_front: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    written_check_front: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    written_check_back: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    set_model: Mapped[SetModel] = relationship(back_populates="cards", foreign_keys=[set_id])
    accepted_answers: Mapped[list["AcceptedAnswer"]] = relationship(
        back_populates="card", cascade="all, delete-orphan", order_by="AcceptedAnswer.position"
    )


class AcceptedAnswer(Base, UuidPk):
    __tablename__ = "accepted_answers"
    __table_args__ = (UniqueConstraint("card_id", "side", "answer", name="uq_accepted_answer"),)

    card_id: Mapped[str] = mapped_column(String(32), ForeignKey("cards.id", ondelete="CASCADE"), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(8), nullable=False)  # front|back — сторона-ответ
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    card: Mapped[Card] = relationship(back_populates="accepted_answers")


class Tag(Base, TimestampMixin, UuidPk):
    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("owner_id", "name_normalized", name="uq_tag_owner_name"),)

    owner_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    name_normalized: Mapped[str] = mapped_column(String(64), nullable=False)


class SetTag(Base, UuidPk):
    __tablename__ = "set_tags"
    __table_args__ = (UniqueConstraint("set_id", "tag_id", name="uq_set_tag"),)

    set_id: Mapped[str] = mapped_column(String(32), ForeignKey("sets.id", ondelete="CASCADE"), nullable=False, index=True)
    tag_id: Mapped[str] = mapped_column(String(32), ForeignKey("tags.id", ondelete="CASCADE"), nullable=False)


class Folder(Base, TimestampMixin, UuidPk):
    __tablename__ = "folders"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_folder_user_name"),)

    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_by_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class FolderSet(Base, UuidPk):
    __tablename__ = "folder_sets"
    __table_args__ = (UniqueConstraint("folder_id", "set_id", name="uq_folder_set"),)

    folder_id: Mapped[str] = mapped_column(String(32), ForeignKey("folders.id", ondelete="CASCADE"), nullable=False, index=True)
    set_id: Mapped[str] = mapped_column(String(32), ForeignKey("sets.id", ondelete="CASCADE"), nullable=False)


class SetPermission(Base, UuidPk):
    __tablename__ = "set_permissions"
    __table_args__ = (
        Index("ix_set_permissions_user_set", "user_id", "set_id"),
        UniqueConstraint("set_id", "user_id", "source", "share_link_id", name="uq_set_permission"),
    )

    set_id: Mapped[str] = mapped_column(String(32), ForeignKey("sets.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    permission: Mapped[str] = mapped_column(String(16), default="reader", nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)  # direct|share_link
    share_link_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("share_links.id", ondelete="CASCADE"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)



class ShareLink(Base, UuidPk):
    __tablename__ = "share_links"

    set_id: Mapped[str] = mapped_column(String(32), ForeignKey("sets.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_by: Mapped[str] = mapped_column(String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Media(Base, UuidPk):
    __tablename__ = "media"

    owner_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    storage_key: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(String(16), nullable=False)  # image|audio
    mime_type: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class CardMedia(Base, UuidPk):
    __tablename__ = "card_media"
    __table_args__ = (UniqueConstraint("card_id", "side", "media_id", name="uq_card_media"),)

    card_id: Mapped[str] = mapped_column(String(32), ForeignKey("cards.id", ondelete="CASCADE"), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    media_id: Mapped[str] = mapped_column(String(32), ForeignKey("media.id", ondelete="CASCADE"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class SnapshotMedia(Base, UuidPk):
    __tablename__ = "snapshot_media"
    __table_args__ = (UniqueConstraint("study_session_id", "media_id", name="uq_snapshot_media"),)

    study_session_id: Mapped[str] = mapped_column(String(32), ForeignKey("study_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    media_id: Mapped[str] = mapped_column(String(32), ForeignKey("media.id", ondelete="CASCADE"), nullable=False)
