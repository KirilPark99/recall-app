"""Общие зависимости: БД, сессии, CSRF, текущий пользователь."""
from __future__ import annotations

from datetime import timedelta
from typing import AsyncIterator

from fastapi import Depends, Request, Response
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_sessionmaker
from app.core.errors import ApiError
from app.core.security import constant_time_equals, hash_token
from app.db.base import utcnow
from app.models import Session as DbSession, User

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


async def get_db() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session


def client_ip(request: Request) -> str | None:
    peer = request.client.host if request.client else None
    fwd = request.headers.get("x-forwarded-for")
    if fwd and peer in settings.trusted_proxy_ips_set:
        return fwd.split(",")[0].strip()[:64]
    return peer


async def load_session(request: Request, db: AsyncSession) -> DbSession | None:
    raw = request.cookies.get(settings.session_cookie_name)
    if not raw:
        return None
    sess = (
        await db.execute(select(DbSession).where(DbSession.token_hash == hash_token(raw)))
    ).scalar_one_or_none()
    if sess is None:
        return None
    now = utcnow()
    if sess.revoked_at is not None or sess.expires_at <= now:
        return None
    if (now - sess.last_seen_at).total_seconds() > 60:
        await db.execute(
            update(DbSession).where(DbSession.id == sess.id).values(last_seen_at=now)
        )
        await db.commit()
    request.state.session = sess
    return sess


async def require_session(request: Request, db: AsyncSession = Depends(get_db)) -> DbSession:
    sess = await load_session(request, db)
    if sess is None:
        raise ApiError(401, "AUTH_REQUIRED", "Требуется вход.")
    return sess


async def require_authenticated_session(
    request: Request, db: AsyncSession = Depends(get_db)
) -> DbSession:
    sess = await require_session(request, db)
    if sess.kind != "authenticated":
        raise ApiError(401, "AUTH_REQUIRED", "Требуется вход.")
    return sess


async def verify_csrf(
    request: Request, sess: DbSession = Depends(require_session)
) -> DbSession:
    if request.method in UNSAFE_METHODS:
        header = request.headers.get("x-csrf-token", "")
        if not header or not constant_time_equals(hash_token(header), sess.csrf_hash):
            raise ApiError(403, "CSRF_INVALID", "Недействительный CSRF-токен.")
        origin = request.headers.get("origin")
        if origin:
            base = str(request.base_url).rstrip("/")
            allowed = {base, settings.app_base_url.rstrip("/"), *settings.cors_origins_list}
            if origin.rstrip("/") not in allowed:
                raise ApiError(403, "ORIGIN_INVALID", "Запрос с недопустимого источника.")
    return sess


async def get_current_user(
    sess: DbSession = Depends(verify_csrf), db: AsyncSession = Depends(get_db)
) -> User:
    user: User | None = None
    if sess.user_id:
        user = await db.get(User, sess.user_id)
    if user is None or sess.kind != "authenticated":
        raise ApiError(401, "AUTH_REQUIRED", "Требуется вход.")
    if not user.is_active:
        raise ApiError(403, "USER_BLOCKED", "Учётная запись заблокирована.")
    return user


async def get_admin_user(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise ApiError(403, "FORBIDDEN", "Требуются права администратора.")
    return user


def set_session_cookie(response: Response, token: str, max_age: int) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=settings.use_secure_cookie,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=settings.session_cookie_name, path="/")


def new_expiry(kind: str):
    ttl = settings.session_ttl_seconds if kind == "authenticated" else settings.pre_auth_ttl_seconds
    return utcnow() + timedelta(seconds=ttl)
