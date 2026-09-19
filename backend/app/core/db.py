"""Асинхронный движок SQLite, прагмы подключения, фабрика сессий."""
from __future__ import annotations

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _connect_pragmas(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute(f"PRAGMA journal_mode={_wal_mode()}")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute(f"PRAGMA busy_timeout={settings.sqlite_busy_timeout_ms}")
    sync = settings.sqlite_synchronous.upper()
    if sync in ("FULL", "NORMAL", "EXTRA"):
        cursor.execute(f"PRAGMA synchronous={sync}")
    cursor.close()


def _wal_mode() -> str:
    # WAL включается на уровне файла базы; для :memory: он недоступен.
    return "WAL" if not str(settings.database_path).startswith("file::memory") else "MEMORY"


def get_engine() -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is None:
        _engine = create_async_engine(
            f"sqlite+aiosqlite:///{settings.database_path}",
            connect_args={"timeout": settings.sqlite_busy_timeout_ms / 1000},
        )
        event.listen(_engine.sync_engine, "connect", _connect_pragmas)
        _sessionmaker = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


def reset_engine_for_tests(db_path: str) -> async_sessionmaker[AsyncSession]:
    """Отдельная фабрика для тестов (временный файл базы)."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", connect_args={"timeout": 5})
    event.listen(engine.sync_engine, "connect", _connect_pragmas)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _sessionmaker = None


async def migrations_ready() -> bool:
    """Проверка Alembic head и ссылочной целостности."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import inspect as sa_inspect
    from app.core.config import PROJECT_ROOT

    config = Config(str(PROJECT_ROOT / "backend" / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "backend" / "alembic"))
    heads = set(ScriptDirectory.from_config(config).get_heads())

    engine = get_engine()
    async with engine.connect() as conn:
        def _check(sync_conn) -> bool:
            insp = sa_inspect(sync_conn)
            if not insp.has_table("alembic_version"):
                return False
            current = {row[0] for row in sync_conn.execute(text("SELECT version_num FROM alembic_version"))}
            if current != heads:
                return False
            return sync_conn.execute(text("PRAGMA foreign_key_check")).fetchone() is None

        return await conn.run_sync(_check)
