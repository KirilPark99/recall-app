"""Схемы авторизации и профиля."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    role: str
    preferred_locale: str
    timezone: str
    theme: str


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: str
    created_at: datetime
    expires_at: datetime
    last_seen_at: datetime
    user_agent: str | None = None
    ip: str | None = None
    is_current: bool = False


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class RegisterRequest(LoginRequest):
    locale: Literal["ru", "en"] = "ru"


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


class CsrfOut(BaseModel):
    csrf_token: str
    expires_in: int


class LoginOut(BaseModel):
    user: UserOut
    csrf_token: str


class PreferencesOut(BaseModel):
    daily_goal_reviews: int
    daily_goal_minutes: int
    daily_goal_new_cards: int
    batch_size: int = 7
    goals_enabled: bool
    streak_enabled: bool
    sound_enabled: bool
    autoplay_audio: bool
    volume: float
    tts_rate: float
    prefer_local_voices: bool
    allow_network_voices: bool
    default_direction: str
    normalization_policy: str
    font_scale: float
    reduced_motion: bool


class PreferencesPatch(BaseModel):
    daily_goal_reviews: int | None = Field(default=None, ge=0, le=1000)
    daily_goal_minutes: int | None = Field(default=None, ge=0, le=600)
    daily_goal_new_cards: int | None = Field(default=None, ge=0, le=500)
    batch_size: int | None = Field(default=None, ge=3, le=50)
    goals_enabled: bool | None = None
    streak_enabled: bool | None = None
    sound_enabled: bool | None = None
    autoplay_audio: bool | None = None
    volume: float | None = Field(default=None, ge=0, le=1)
    tts_rate: float | None = Field(default=None, ge=0.5, le=2.0)
    prefer_local_voices: bool | None = None
    allow_network_voices: bool | None = None
    default_direction: Literal["front_to_back", "back_to_front", "both"] | None = None
    normalization_policy: Literal["default", "strict", "lenient"] | None = None
    font_scale: float | None = Field(default=None, ge=0.8, le=1.5)
    reduced_motion: bool | None = None


class MePatch(BaseModel):
    preferred_locale: Literal["ru", "en"] | None = None
    timezone: str | None = Field(default=None, max_length=64)
    theme: Literal["light", "dark", "system"] | None = None
    username: str | None = Field(default=None, min_length=2, max_length=64)
