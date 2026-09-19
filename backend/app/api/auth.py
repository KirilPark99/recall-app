"""Авторизация: CSRF bootstrap, вход, регистрация, сессии, пароль."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    clear_session_cookie,
    client_ip,
    get_current_user,
    get_db,
    new_expiry,
    set_session_cookie,
    verify_csrf,
)
from app.core.config import settings
from app.core.errors import ApiError
from app.core.ratelimit import check_rate_limit
from app.core.security import derive_csrf_token, generate_token, hash_password, hash_token, verify_password
from app.db.base import utcnow
from app.models import AuditEvent, Session as DbSession, User
from app.schemas.auth import (
    ChangePasswordRequest,
    CsrfOut,
    LoginOut,
    LoginRequest,
    RegisterRequest,
    SessionOut,
    UserOut,
)
from app.services.settings_service import get_setting, ensure_defaults_for_user

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_meta(request: Request) -> tuple[str | None, str | None]:
    return request.headers.get("user-agent", "")[:300] or None, client_ip(request)


async def _create_session(
    db: AsyncSession, kind: str, user_id: str | None, request: Request
) -> tuple[DbSession, str, str]:
    """Создаёт сессию; возвращает (сессию, сырой токен для cookie, csrf-токен)."""
    token = generate_token()
    token_hash = hash_token(token)
    csrf_token = derive_csrf_token(token_hash)
    ua, ip = _client_meta(request)
    sess = DbSession(
        user_id=user_id,
        kind=kind,
        token_hash=token_hash,
        csrf_hash=hash_token(csrf_token),
        expires_at=new_expiry(kind),
        user_agent=ua,
        ip=ip,
    )
    db.add(sess)
    await db.commit()
    await db.refresh(sess)
    return sess, token, csrf_token


async def cleanup_stale_sessions(db: AsyncSession) -> int:
    """Удаляет просроченные и отозванные сессии из БД."""
    result = await db.execute(
        delete(DbSession).where(
            (DbSession.expires_at < utcnow()) | (DbSession.revoked_at.is_not(None))
        )
    )
    return result.rowcount


@router.get("/csrf", response_model=CsrfOut)
async def get_csrf(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Bootstrap до входа: pre-auth сессия + CSRF-токен.

    Если у клиента уже есть действующая сессия (в том числе авторизованная),
    она сохраняется и возвращается её CSRF-токен — перезагрузка страницы
    не разлогинивает и не ломает параллельные вкладки.
    """
    from app.api.deps import load_session

    sess = await load_session(request, db)
    if sess is not None:
        # Токен детерминирован по сессии: идемпотентно мигрирует старые записи,
        # не ротируется на каждый запрос (параллельные вкладки не ломаются).
        derived = derive_csrf_token(sess.token_hash)
        expected_hash = hash_token(derived)
        if sess.csrf_hash != expected_hash:
            sess.csrf_hash = expected_hash
            await db.commit()
        return CsrfOut(
            csrf_token=derived,
            expires_in=int((sess.expires_at - utcnow()).total_seconds()),
        )
    _, token, csrf_token = await _create_session(db, "pre_auth", None, request)
    set_session_cookie(response, token, settings.pre_auth_ttl_seconds)
    return CsrfOut(csrf_token=csrf_token, expires_in=settings.pre_auth_ttl_seconds)


@router.post("/login", response_model=LoginOut)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    _sess: DbSession = Depends(verify_csrf),
):
    ip = client_ip(request) or "unknown"
    check_rate_limit(f"login:{ip}", settings.rate_limit_login_attempts, settings.rate_limit_login_window_seconds)
    check_rate_limit(
        f"login:{ip}:{payload.username.strip().lower()}",
        settings.rate_limit_login_attempts,
        settings.rate_limit_login_window_seconds,
    )
    normalized = payload.username.strip().lower()
    user = (
        await db.execute(select(User).where(User.username_normalized == normalized))
    ).scalar_one_or_none()
    if user is None or not verify_password(user.password_hash, payload.password):
        # Одинаковый ответ для несуществующего пользователя и неверного пароля.
        raise ApiError(401, "INVALID_CREDENTIALS", "Неверное имя пользователя или пароль.")
    if not user.is_active:
        raise ApiError(403, "USER_BLOCKED", "Учётная запись заблокирована. Обратитесь к администратору.")
    await _revoke_cookie_session(db, request)
    sess, token, csrf_token = await _create_session(db, "authenticated", user.id, request)
    await cleanup_stale_sessions(db)
    await db.execute(update(User).where(User.id == user.id).values(last_login_at=utcnow()))
    await db.commit()
    set_session_cookie(response, token, settings.session_ttl_seconds)
    return LoginOut(user=UserOut.model_validate(user), csrf_token=csrf_token)


@router.post("/register", response_model=LoginOut)
async def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    _sess: DbSession = Depends(verify_csrf),
):
    if not await get_setting(db, "registration_enabled", False):
        raise ApiError(403, "REGISTRATION_DISABLED", "Регистрация отключена администратором.")
    check_rate_limit(
        f"register:{client_ip(request) or 'unknown'}", 10, settings.rate_limit_login_window_seconds
    )
    username = payload.username.strip()
    normalized = username.lower()
    exists = (
        await db.execute(select(User.id).where(User.username_normalized == normalized))
    ).scalar_one_or_none()
    if exists:
        raise ApiError(409, "USERNAME_TAKEN", "Это имя пользователя уже занято.")
    user = User(
        username=username,
        username_normalized=normalized,
        password_hash=hash_password(payload.password),
        role="user",
        preferred_locale=payload.locale,
        timezone=settings.default_timezone,
    )
    db.add(user)
    await db.flush()
    await ensure_defaults_for_user(db, user.id)
    await _revoke_cookie_session(db, request)
    sess, token, csrf_token = await _create_session(db, "authenticated", user.id, request)
    await db.commit()
    set_session_cookie(response, token, settings.session_ttl_seconds)
    return LoginOut(user=UserOut.model_validate(user), csrf_token=csrf_token)


async def _revoke_cookie_session(db: AsyncSession, request: Request) -> None:
    old = request.cookies.get(settings.session_cookie_name)
    if old:
        await db.execute(
            update(DbSession).where(DbSession.token_hash == hash_token(old)).values(revoked_at=utcnow())
        )


@router.post("/logout")
async def logout(
    response: Response,
    db: AsyncSession = Depends(get_db),
    sess: DbSession = Depends(verify_csrf),
):
    await db.execute(update(DbSession).where(DbSession.id == sess.id).values(revoked_at=utcnow()))
    await db.commit()
    clear_session_cookie(response)
    return {"ok": True}


class LogoutAllRequest(BaseModel):
    keep_current: bool = False


@router.post("/logout-all")
async def logout_all(
    request: Request,
    response: Response,
    payload: LogoutAllRequest | None = None,
    keep_current: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    should_keep = keep_current or (payload.keep_current if payload else False)
    current = getattr(request.state, "session", None)

    stmt = update(DbSession).where(
        DbSession.user_id == user.id,
        DbSession.kind == "authenticated",
        DbSession.revoked_at.is_(None),
    )
    if should_keep and current:
        stmt = stmt.where(DbSession.id != current.id)

    result = await db.execute(stmt.values(revoked_at=utcnow()))
    await cleanup_stale_sessions(db)
    await db.commit()
    if not should_keep:
        clear_session_cookie(response)
    return {"ok": True, "revoked": result.rowcount}


@router.post("/sessions/revoke-others")
@router.delete("/sessions/others")
async def revoke_other_sessions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    sess: DbSession = Depends(verify_csrf),
):
    result = await db.execute(
        update(DbSession)
        .where(
            DbSession.user_id == user.id,
            DbSession.kind == "authenticated",
            DbSession.revoked_at.is_(None),
            DbSession.id != sess.id,
        )
        .values(revoked_at=utcnow())
    )
    await cleanup_stale_sessions(db)
    await db.commit()
    return {"ok": True, "revoked": result.rowcount}


@router.post("/sessions/cleanup")
async def manual_session_cleanup(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
    _sess: DbSession = Depends(verify_csrf),
):
    count = await cleanup_stale_sessions(db)
    await db.commit()
    return {"ok": True, "deleted": count}


@router.get("/sessions", response_model=list[SessionOut])
async def list_sessions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await cleanup_stale_sessions(db)
    await db.commit()
    current = getattr(request.state, "session", None)
    rows = (
        await db.execute(
            select(DbSession)
            .where(
                DbSession.user_id == user.id,
                DbSession.kind == "authenticated",
                DbSession.revoked_at.is_(None),
                DbSession.expires_at > utcnow(),
            )
            .order_by(DbSession.last_seen_at.desc())
        )
    ).scalars().all()
    out = []
    for s in rows:
        item = SessionOut.model_validate(s)
        item.is_current = bool(current and s.id == current.id)
        out.append(item)
    return out


@router.delete("/sessions/{session_id}")
async def revoke_session(
    session_id: str,
    response: Response,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    sess: DbSession = Depends(verify_csrf),
):
    result = await db.execute(
        update(DbSession)
        .where(
            DbSession.id == session_id,
            DbSession.user_id == user.id,
            DbSession.revoked_at.is_(None),
        )
        .values(revoked_at=utcnow())
    )
    if result.rowcount == 0:
        raise ApiError(404, "NOT_FOUND", "Сессия не найдена.")
    await cleanup_stale_sessions(db)
    await db.commit()
    if session_id == sess.id:
        clear_session_cookie(response)
    return {"ok": True}


@router.post("/change-password")
async def change_password(
    payload: ChangePasswordRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    sess: DbSession = Depends(verify_csrf),
):
    if not verify_password(user.password_hash, payload.current_password):
        raise ApiError(400, "WRONG_PASSWORD", "Текущий пароль указан неверно.")
    await db.execute(update(User).where(User.id == user.id).values(password_hash=hash_password(payload.new_password)))
    await db.execute(
        update(DbSession)
        .where(
            DbSession.user_id == user.id,
            DbSession.kind == "authenticated",
            DbSession.revoked_at.is_(None),
            DbSession.id != sess.id,
        )
        .values(revoked_at=utcnow())
    )
    db.add(AuditEvent(actor_id=user.id, action="change_password", target_type="user", target_id=user.id))
    await db.commit()
    return {"ok": True}
