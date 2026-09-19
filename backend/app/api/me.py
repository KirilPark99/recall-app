"""Текущий пользователь, настройки, активность."""
from __future__ import annotations

from datetime import timezone as dt_timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.api.deps import get_current_user, get_db
from app.core.errors import ApiError
from app.models import ActivityEvent, User, UserPreferences
from app.schemas.auth import MePatch, PreferencesOut, PreferencesPatch, UserOut

router = APIRouter(tags=["me"])


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return UserOut.model_validate(user)


@router.patch("/me", response_model=UserOut)
async def patch_me(
    payload: MePatch,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    data = payload.model_dump(exclude_unset=True)
    if "timezone" in data and data["timezone"]:
        try:
            ZoneInfo(data["timezone"])
        except (ZoneInfoNotFoundError, KeyError, ValueError):
            raise ApiError(422, "VALIDATION_ERROR", "Неизвестный часовой пояс.", {"items": [{"field": "timezone"}]})
    if "username" in data and data["username"]:
        normalized = data["username"].strip().lower()
        exists = (
            await db.execute(
                select(User.id).where(User.username_normalized == normalized, User.id != user.id)
            )
        ).scalar_one_or_none()
        if exists:
            raise ApiError(409, "USERNAME_TAKEN", "Это имя пользователя уже занято.")
        data["username"] = data["username"].strip()
        data["username_normalized"] = normalized
    for key, value in data.items():
        setattr(user, key, value)
    await db.commit()
    await db.refresh(user)
    return UserOut.model_validate(user)


async def get_preferences(db: AsyncSession, user_id: str) -> UserPreferences:
    row = (
        await db.execute(select(UserPreferences).where(UserPreferences.user_id == user_id))
    ).scalar_one_or_none()
    if row is None:
        row = UserPreferences(user_id=user_id)
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row


@router.get("/me/preferences", response_model=PreferencesOut)
async def my_preferences(
    db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    prefs = await get_preferences(db, user.id)
    return PreferencesOut(
        daily_goal_reviews=prefs.daily_goal_reviews,
        daily_goal_minutes=prefs.daily_goal_minutes,
        daily_goal_new_cards=prefs.daily_goal_new_cards,
        batch_size=prefs.batch_size,
        goals_enabled=prefs.goals_enabled,
        streak_enabled=prefs.streak_enabled,
        sound_enabled=prefs.sound_enabled,
        autoplay_audio=prefs.autoplay_audio,
        volume=prefs.volume,
        tts_rate=prefs.tts_rate,
        prefer_local_voices=prefs.prefer_local_voices,
        allow_network_voices=prefs.allow_network_voices,
        default_direction=prefs.default_direction,
        normalization_policy=prefs.normalization_policy,
        font_scale=prefs.font_scale,
        reduced_motion=prefs.reduced_motion,
    )


@router.patch("/me/preferences", response_model=PreferencesOut)
async def patch_preferences(
    payload: PreferencesPatch,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    prefs = await get_preferences(db, user.id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(prefs, key, value)
    await db.commit()
    await db.refresh(prefs)
    return await my_preferences(db=db, user=user)


@router.get("/me/activity")
async def my_activity(
    limit: int = 30,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    limit = min(max(limit, 1), 90)
    rows = (
        await db.execute(
            select(ActivityEvent)
            .where(ActivityEvent.user_id == user.id)
            .order_by(ActivityEvent.occurred_at_utc.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [
        {
            "id": r.id,
            "event_type": r.event_type,
            "occurred_at_utc": r.occurred_at_utc.replace(tzinfo=dt_timezone.utc).isoformat(),
            "local_date": r.local_date,
            "set_id": r.set_id,
            "card_id": r.card_id,
        }
        for r in rows
    ]
