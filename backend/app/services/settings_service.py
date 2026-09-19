"""Настройки сервера и пользовательские дефолты."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ServerSetting, SrsSettings, UserPreferences

DEFAULTS: dict[str, Any] = {
    "registration_enabled": False,
    "quizlet_proxy_url": "",
    "quizlet_headless": True,
}


async def get_setting(db: AsyncSession, key: str, default: Any = None) -> Any:
    row = (await db.execute(select(ServerSetting).where(ServerSetting.key == key))).scalar_one_or_none()
    if row is None:
        return DEFAULTS.get(key, default)
    return json.loads(row.value_json)


async def set_setting(db: AsyncSession, key: str, value: Any) -> None:
    row = (await db.execute(select(ServerSetting).where(ServerSetting.key == key))).scalar_one_or_none()
    payload = json.dumps(value, ensure_ascii=False)
    if row is None:
        db.add(ServerSetting(key=key, value_json=payload))
    else:
        row.value_json = payload
    await db.commit()


async def ensure_defaults_for_user(db: AsyncSession, user_id: str) -> None:
    db.add(UserPreferences(user_id=user_id))
    db.add(SrsSettings(user_id=user_id))
    await db.flush()
