"""CLI приложения: create-admin, seed-demo, backup, maintenance."""
from __future__ import annotations

import asyncio
import getpass
import sys

import click

from app.core.config import ensure_dirs
from app.core.db import get_sessionmaker


@click.group()
def cli() -> None:
    """Recall — команды управления сервером."""


@cli.command()
@click.option("--username", "-u", default=None, help="Имя пользователя администратора.")
@click.option("--password", "-p", default=None, help="Пароль администратора (минимум 8 символов).")
def create_admin(username: str | None, password: str | None) -> None:
    """Создание учётной записи администратора (интерактивно или через аргументы)."""

    async def run() -> None:
        ensure_dirs()
        from sqlalchemy import select

        from app.core.security import hash_password
        from app.models import User
        from app.services.settings_service import ensure_defaults_for_user

        nonlocal username, password

        if not username:
            username = click.prompt("Имя пользователя", type=str).strip()
        else:
            username = username.strip()

        if not username or len(username) > 64:
            click.echo("Некорректное имя пользователя (1-64 символа).")
            sys.exit(1)

        if not password:
            while True:
                p1 = getpass.getpass("Пароль (минимум 8 символов): ")
                if len(p1) < 8:
                    click.echo("Пароль слишком короткий (минимум 8 символов).")
                    continue
                p2 = getpass.getpass("Повторите пароль: ")
                if p1 != p2:
                    click.echo("Пароли не совпадают.")
                    continue
                password = p1
                break
        else:
            if len(password) < 8:
                click.echo("Пароль слишком короткий (минимум 8 символов).")
                sys.exit(1)

        async with get_sessionmaker()() as db:
            existing = (
                await db.execute(select(User).where(User.username_normalized == username.lower()))
            ).scalar_one_or_none()

            if existing:
                existing.role = "admin"
                existing.is_active = True
                existing.password_hash = hash_password(password)
                await ensure_defaults_for_user(db, existing.id)
                await db.commit()
                click.echo(f"Пользователь «{existing.username}» обновлён и назначен администратором.")
                return

            user = User(
                username=username,
                username_normalized=username.lower(),
                password_hash=hash_password(password),
                role="admin",
            )
            db.add(user)
            await db.flush()
            await ensure_defaults_for_user(db, user.id)
            await db.commit()
            click.echo(f"Администратор «{username}» успешно создан.")

    asyncio.run(run())


@cli.command()
@click.option("--username", "-u", default=None, help="Имя пользователя для смены пароля.")
@click.option("--password", "-p", default=None, help="Новый пароль (минимум 8 символов).")
def reset_password(username: str | None, password: str | None) -> None:
    """Сброс пароля любого пользователя или администратора."""

    async def run() -> None:
        ensure_dirs()
        from sqlalchemy import select

        from app.core.security import hash_password
        from app.models import User

        nonlocal username, password

        if not username:
            username = click.prompt("Имя пользователя", type=str).strip()
        else:
            username = username.strip()

        if not password:
            while True:
                p1 = getpass.getpass("Новый пароль (минимум 8 символов): ")
                if len(p1) < 8:
                    click.echo("Пароль слишком короткий (минимум 8 символов).")
                    continue
                p2 = getpass.getpass("Повторите пароль: ")
                if p1 != p2:
                    click.echo("Пароли не совпадают.")
                    continue
                password = p1
                break
        else:
            if len(password) < 8:
                click.echo("Пароль слишком короткий (минимум 8 символов).")
                sys.exit(1)

        async with get_sessionmaker()() as db:
            user = (
                await db.execute(select(User).where(User.username_normalized == username.lower()))
            ).scalar_one_or_none()

            if not user:
                click.echo(f"Пользователь «{username}» не найден.")
                sys.exit(1)

            user.password_hash = hash_password(password)
            await db.commit()
            click.echo(f"Пароль для пользователя «{user.username}» успешно изменён.")

    asyncio.run(run())


@cli.command()
@click.option("--owner", "owner_username", required=True, help="Имя пользователя-владельца демо-наборов.")
def seed_demo(owner_username: str) -> None:
    """Добавляет небольшие оригинальные демонстрационные наборы указанному владельцу."""

    async def run() -> None:
        ensure_dirs()
        from sqlalchemy import select

        from app.models import User
        from app.services.demo_seed import seed_demo_sets

        async with get_sessionmaker()() as db:
            user = (
                await db.execute(select(User).where(User.username_normalized == owner_username.lower()))
            ).scalar_one_or_none()
            if user is None:
                click.echo(f"Пользователь «{owner_username}» не найден.")
                sys.exit(1)
            created = await seed_demo_sets(db, user)
            click.echo(f"Создано наборов: {created}")

    asyncio.run(run())


# Регистрация групп backup/maintenance добавляется в cli_backup.py
from app.cli_backup import register_backup_commands  # noqa: E402

register_backup_commands(cli)

if __name__ == "__main__":
    cli()
