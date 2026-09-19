"""Alembic environment: целевая схема из app.models, URL из настроек приложения."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alembic import context  # noqa: E402
from sqlalchemy import pool  # noqa: E402
from sqlalchemy import engine_from_config  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core import db as core_db  # noqa: E402
from app.models import *  # noqa: F401,F403
from app.db.base import Base  # noqa: E402

settings.data_dir_path.mkdir(parents=True, exist_ok=True)

config = context.config
config.set_main_option("sqlalchemy.url", f"sqlite:///{settings.database_path}")
target_metadata = Base.metadata

# Прагмы применяются к каждому подключению (включая офлайн-миграции).


def _set_pragmas(dbapi_connection, _rec):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    cfg = config.get_section(config.config_ini_section, {})
    engine = engine_from_config(cfg, prefix="sqlalchemy.", poolclass=pool.NullPool)
    from sqlalchemy import event

    event.listen(engine, "connect", _set_pragmas)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # SQLite: ALTER через пакетную перезапись
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
