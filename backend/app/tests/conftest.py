"""Общие фикстуры: временная база с миграциями, пользователи, API-клиент."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("RECALL_TEST", "1")

from app.core import config as cfg  # noqa: E402
from app.core import db as core_db  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models import User, UserPreferences, SrsSettings  # noqa: E402


pytest_plugins = ("pytest_asyncio",)


@pytest_asyncio.fixture
async def test_db(tmp_path: Path):
    """Временный файл SQLite (не in-memory) с применёнными миграциями."""
    db_path = tmp_path / "app.sqlite3"
    original_data_dir = cfg.settings.data_dir
    cfg.settings.data_dir = str(tmp_path)
    from alembic import command
    from alembic.config import Config

    alembic_cfg = Config(str(cfg.PROJECT_ROOT / "backend" / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(cfg.PROJECT_ROOT / "backend" / "alembic"))
    command.upgrade(alembic_cfg, "head")
    sessionmaker = core_db.reset_engine_for_tests(str(db_path))
    engine = sessionmaker.kw["bind"]
    try:
        yield sessionmaker
    finally:
        await engine.dispose()
        cfg.settings.data_dir = original_data_dir


@pytest_asyncio.fixture
async def users(test_db):
    """admin, alice (владелец), bob (читатель), carol (посторонний)."""
    async with test_db() as db:
        rows = {}
        for username, role in (("admin", "admin"), ("alice", "user"), ("bob", "user"), ("carol", "user")):
            user = User(
                username=username,
                username_normalized=username,
                password_hash=hash_password(f"pass-{username}-123"),
                role=role,
            )
            db.add(user)
            await db.flush()
            db.add(UserPreferences(user_id=user.id))
            db.add(SrsSettings(user_id=user.id))
            rows[username] = user
        await db.commit()
        return {k: v.id for k, v in rows.items()}


class Api:
    """Тестовый клиент с cookie-сессией и CSRF."""

    def __init__(self, client: AsyncClient):
        self.client = client

    async def bootstrap(self) -> str:
        r = await self.client.get("/api/v1/auth/csrf")
        return r.json()["csrf_token"]

    async def login(self, username: str, password: str) -> str:
        csrf = await self.bootstrap()
        r = await self.client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": password},
            headers={"X-CSRF-Token": csrf},
        )
        assert r.status_code == 200, r.text
        return r.json()["csrf_token"]

    async def get(self, path: str, **kw):
        return await self.client.get(f"/api/v1{path}", **kw)

    async def post(self, path: str, json=None, csrf: str | None = None, **kw):
        token = csrf or await self.bootstrap()
        return await self.client.post(f"/api/v1{path}", json=json, headers={"X-CSRF-Token": token}, **kw)

    async def put(self, path: str, json=None, csrf: str | None = None):
        token = csrf or await self.bootstrap()
        return await self.client.put(f"/api/v1{path}", json=json, headers={"X-CSRF-Token": token})

    async def patch(self, path: str, json=None, csrf: str | None = None):
        token = csrf or await self.bootstrap()
        return await self.client.patch(f"/api/v1{path}", json=json, headers={"X-CSRF-Token": token})

    async def delete(self, path: str, csrf: str | None = None):
        token = csrf or await self.bootstrap()
        return await self.client.delete(f"/api/v1{path}", headers={"X-CSRF-Token": token})


@pytest_asyncio.fixture
async def api_factory(test_db):
    """Создаёт независимые сессии-клиенты (по одному на пользователя)."""
    from app.main import app

    transport = ASGITransport(app=app)
    # Подменяем фабрику сессий на тестовую базу.
    import app.api.deps as deps

    original = deps.get_sessionmaker
    deps.get_sessionmaker = lambda: test_db

    async def make_api() -> Api:
        from app.core.ratelimit import clear_rate_limits

        clear_rate_limits()
        client = AsyncClient(transport=transport, base_url="http://testserver")
        return Api(client)

    yield make_api
    deps.get_sessionmaker = original


@pytest_asyncio.fixture
async def alice(api_factory, users):
    api = await api_factory()
    await api.login("alice", "pass-alice-123")
    return api


@pytest_asyncio.fixture
async def bob(api_factory, users):
    api = await api_factory()
    await api.login("bob", "pass-bob-123")
    return api


@pytest_asyncio.fixture
async def carol(api_factory, users):
    api = await api_factory()
    await api.login("carol", "pass-carol-123")
    return api


@pytest_asyncio.fixture
async def admin(api_factory, users):
    api = await api_factory()
    await api.login("admin", "pass-admin-123")
    return api


@pytest_asyncio.fixture
async def demo_set(alice):
    """Набор alice с 6 карточками."""
    r = await alice.post(
        "/sets",
        json={
            "title": "Alice demo",
            "front_language": "en",
            "back_language": "ru",
            "cards": [
                {"front_text": "apple", "back_text": "яблоко", "front_hint": "фрукт"},
                {"front_text": "dog", "back_text": "собака"},
                {"front_text": "sun", "back_text": "солнце"},
                {"front_text": "book", "back_text": "книга"},
                {"front_text": "water", "back_text": "вода"},
                {"front_text": "tree", "back_text": "дерево"},
            ],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()
