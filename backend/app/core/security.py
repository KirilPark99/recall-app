"""Пароли (Argon2id), токены и их хеши."""
from __future__ import annotations

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError

_hasher = PasswordHasher()  # Argon2id по умолчанию


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def generate_token() -> str:
    """Криптографически случайный непрозрачный токен (сессии, share-ссылки)."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def derive_csrf_token(session_token_hash: str) -> str:
    """CSRF-токен выводится из хеша сессионного токена (HMAC).

    Клиент получает его от сервера; cookie HttpOnly, поэтому третьи лица
    и сам клиент без ответа сервера вычислить его не могут. Токен стабилен
    в пределах сессии — параллельные вкладки не ломаются.
    """
    import hmac as _hmac

    return _hmac.new(session_token_hash.encode("utf-8"), b"csrf", hashlib.sha256).hexdigest()
