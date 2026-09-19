"""DTO наборов и карточек."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MediaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    media_type: str
    mime_type: str
    original_name: str
    description: str
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None


class SetListItem(BaseModel):
    id: str
    title: str
    description: str
    front_language: str
    back_language: str
    visibility: str
    archived: bool
    tags: list[str] = []
    card_count: int
    owner_username: str
    is_own: bool
    is_favorite: bool = False
    in_library: bool = False
    in_folder_id: str | None = None
    last_studied_at: datetime | None = None
    updated_at: datetime
    due_count: int | None = None
    content_version: int = 1
    is_admin_created: bool = False


class SetDetail(SetListItem):
    created_at: datetime
    viewer_role: str
    folders: list[str] = []


class SetCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=2000)
    front_language: str = Field(default="", max_length=16)
    back_language: str = Field(default="", max_length=16)
    visibility: Literal["private", "server_public", "link"] = "private"
    tags: list[str] = Field(default_factory=list, max_length=20)
    cards: list["CardIn"] = Field(default_factory=list)


class SetPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=2000)
    front_language: str | None = Field(default=None, max_length=16)
    back_language: str | None = Field(default=None, max_length=16)
    visibility: Literal["private", "server_public", "link"] | None = None
    tags: list[str] | None = Field(default=None, max_length=20)
    expected_content_version: int = Field(ge=1)


class SetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    owner_id: str
    title: str
    description: str
    front_language: str
    back_language: str
    visibility: str
    archived: bool
    content_version: int
    created_at: datetime
    updated_at: datetime


class CardIn(BaseModel):
    """Карточка при создании; id сохраняется при импорте/копировании, иначе генерируется."""

    id: str | None = Field(default=None, max_length=32)
    front_text: str = Field(default="", max_length=10000)
    back_text: str = Field(default="", max_length=10000)
    front_context: str = Field(default="", max_length=500)
    back_context: str = Field(default="", max_length=500)
    front_hint: str = Field(default="", max_length=500)
    back_hint: str = Field(default="", max_length=500)
    front_explanation: str = Field(default="", max_length=5000)
    back_explanation: str = Field(default="", max_length=5000)
    front_example: str = Field(default="", max_length=2000)
    back_example: str = Field(default="", max_length=2000)
    front_language: str | None = Field(default=None, max_length=16)
    back_language: str | None = Field(default=None, max_length=16)
    enabled_front_to_back: bool = True
    enabled_back_to_front: bool = True
    written_check_front: bool = True
    written_check_back: bool = True
    accepted_front: list[str] = Field(default_factory=list, max_length=20)
    accepted_back: list[str] = Field(default_factory=list, max_length=20)


class CardOut(BaseModel):
    id: str
    set_id: str
    position: int
    content_version: int
    front_text: str
    back_text: str
    front_context: str
    back_context: str
    front_hint: str
    back_hint: str
    front_explanation: str
    back_explanation: str
    front_example: str
    back_example: str
    front_language: str | None
    back_language: str | None
    enabled_front_to_back: bool
    enabled_back_to_front: bool
    written_check_front: bool
    written_check_back: bool
    accepted_front: list[str] = []
    accepted_back: list[str] = []
    front_media: list[MediaOut] = []
    back_media: list[MediaOut] = []
    is_starred: bool = False
    updated_at: datetime


class CardListOut(BaseModel):
    items: list[CardOut]
    total: int
    set_content_version: int


class CardPatch(CardIn):
    pass


class BatchCardsIn(BaseModel):
    cards: list[CardIn] = Field(min_length=1, max_length=1000)
    expected_content_version: int | None = Field(default=None, ge=1)


class ReorderIn(BaseModel):
    ordered_ids: list[str] = Field(min_length=1, max_length=5000)
    expected_content_version: int = Field(ge=1)


class BulkIdsIn(BaseModel):
    card_ids: list[str] = Field(min_length=1, max_length=5000)
    expected_content_version: int = Field(ge=1)


class BulkMoveIn(BulkIdsIn):
    target_set_id: str
    target_expected_content_version: int = Field(ge=1)


class SwapSidesIn(BaseModel):
    expected_content_version: int | None = Field(default=None, ge=1)


class OperationResult(BaseModel):
    ok: bool = True
    content_version: int
    applied: int = 0


class FolderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class FolderOut(BaseModel):
    id: str
    name: str
    set_count: int = 0
    created_at: datetime
    created_by_admin: bool = False


class FolderPatch(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class TagOut(BaseModel):
    id: str
    name: str
    set_count: int = 0
