"""Обмен ссылками и прямые разрешения."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.config import settings
from app.core.errors import ApiError
from app.core.ratelimit import check_rate_limit
from app.core.security import generate_token, hash_token
from app.db.base import utcnow
from app.models import SetModel, SetPermission, ShareLink, User
from app.services.access import require_owner
from app.services.share_service import _revoke_link

router = APIRouter(tags=["sharing"])


class ShareLinkCreate(BaseModel):
    expires_in_hours: int | None = Field(default=None, ge=1, le=24 * 365)


class ShareLinkOut(BaseModel):
    id: str
    created_at: object
    expires_at: object | None
    revoked_at: object | None
    token: str | None = None  # только в ответе создания


class RedeemIn(BaseModel):
    token: str = Field(min_length=10, max_length=128)


class RedeemOut(BaseModel):
    set_id: str
    title: str


class PermissionGrantIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)


@router.post("/sets/{set_id}/share-links", response_model=ShareLinkOut, status_code=201)
async def create_share_link(
    set_id: str,
    payload: ShareLinkCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    st = await require_owner(db, user, set_id)
    if st.visibility == "private":
        st.visibility = "link"
    token = generate_token()
    link = ShareLink(
        set_id=st.id,
        token_hash=hash_token(token),
        created_by=user.id,
        revision=st.share_revision,
        expires_at=(utcnow() + timedelta(hours=payload.expires_in_hours)) if payload.expires_in_hours else None,
    )
    db.add(link)
    await db.commit()
    await db.refresh(link)
    return ShareLinkOut(
        id=link.id,
        created_at=link.created_at,
        expires_at=link.expires_at,
        revoked_at=None,
        token=token,
    )


@router.get("/sets/{set_id}/share-links", response_model=list[ShareLinkOut])
async def list_share_links(
    set_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    await require_owner(db, user, set_id)
    rows = (
        await db.execute(
            select(ShareLink)
            .where(ShareLink.set_id == set_id)
            .order_by(ShareLink.created_at.desc())
        )
    ).scalars().all()
    # Токены не возвращаются: только маскированные метаданные.
    return [
        ShareLinkOut(id=l.id, created_at=l.created_at, expires_at=l.expires_at, revoked_at=l.revoked_at)
        for l in rows
    ]


@router.delete("/sets/{set_id}/share-links/{link_id}")
async def revoke_share_link(
    set_id: str,
    link_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await require_owner(db, user, set_id)
    link = (
        await db.execute(
            select(ShareLink).where(ShareLink.id == link_id, ShareLink.set_id == set_id)
        )
    ).scalar_one_or_none()
    if link is None:
        raise ApiError(404, "NOT_FOUND", "Ссылка не найдена.")
    await _revoke_link(db, link)
    await db.commit()
    return {"ok": True}


@router.post("/share-links/redeem", response_model=RedeemOut)
async def redeem(
    payload: RedeemIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.core.ratelimit import check_rate_limit as crl

    from app.api.deps import client_ip

    crl(f"redeem:{user.id}:{client_ip(request)}", settings.rate_limit_redeem_per_window, 60)
    link = (
        await db.execute(select(ShareLink).where(ShareLink.token_hash == hash_token(payload.token.strip())))
    ).scalar_one_or_none()
    # Одинаковый ответ для неверного/просроченного/отозванного токена.
    invalid = ApiError(404, "NOT_FOUND", "Ссылка недействительна.")
    if link is None or link.revoked_at is not None:
        raise invalid
    if link.expires_at is not None and link.expires_at <= utcnow():
        raise invalid
    st = (
        await db.execute(
            select(SetModel).where(SetModel.id == link.set_id, SetModel.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if st is None or st.visibility not in ("link", "server_public") or st.owner_id == user.id:
        raise invalid
    # Обмен токена на проверяемое разрешение: токен больше не нужен клиенту.
    grant = (
        await db.execute(
            select(SetPermission).where(
                SetPermission.set_id == st.id,
                SetPermission.user_id == user.id,
                SetPermission.share_link_id == link.id,
            )
        )
    ).scalar_one_or_none()
    if grant is not None and grant.revoked_at is None:
        return RedeemOut(set_id=st.id, title=st.title)
    if grant is not None:
        grant.revoked_at = None
        await db.commit()
        return RedeemOut(set_id=st.id, title=st.title)
    grant = SetPermission(
        set_id=st.id, user_id=user.id, permission="reader", source="share_link", share_link_id=link.id
    )
    db.add(grant)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = (
            await db.execute(
                select(SetPermission).where(
                    SetPermission.set_id == st.id,
                    SetPermission.user_id == user.id,
                    SetPermission.share_link_id == link.id,
                    SetPermission.revoked_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            raise
    return RedeemOut(set_id=st.id, title=st.title)


@router.get("/sets/{set_id}/permissions")
async def list_permissions(
    set_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    await require_owner(db, user, set_id)
    rows = (
        await db.execute(
            select(SetPermission, User.username)
            .join(User, User.id == SetPermission.user_id)
            .where(SetPermission.set_id == set_id, SetPermission.revoked_at.is_(None))
            .order_by(SetPermission.created_at)
        )
    ).all()
    return [
        {
            "id": p.id,
            "user_id": p.user_id,
            "username": username,
            "permission": p.permission,
            "source": p.source,
            "created_at": p.created_at,
        }
        for p, username in rows
    ]


@router.post("/sets/{set_id}/permissions", status_code=201)
async def grant_permission(
    set_id: str,
    payload: PermissionGrantIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    st = await require_owner(db, user, set_id)
    target = (
        await db.execute(select(User).where(User.username_normalized == payload.username.strip().lower()))
    ).scalar_one_or_none()
    if target is None:
        raise ApiError(404, "NOT_FOUND", "Пользователь не найден.")
    if target.id == user.id:
        raise ApiError(422, "VALIDATION_ERROR", "Нельзя выдать разрешение самому себе.")
    exists = (
        await db.execute(
            select(SetPermission).where(
                SetPermission.set_id == st.id,
                SetPermission.user_id == target.id,
                SetPermission.source == "direct",
                SetPermission.revoked_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if exists is None:
        db.add(SetPermission(set_id=st.id, user_id=target.id, permission="reader", source="direct"))
        await db.commit()
    return {"ok": True, "user_id": target.id, "username": target.username}


@router.delete("/sets/{set_id}/permissions/{grant_id}")
async def revoke_permission(
    set_id: str,
    grant_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await require_owner(db, user, set_id)
    grant = (
        await db.execute(
            select(SetPermission).where(
                SetPermission.id == grant_id, SetPermission.set_id == set_id, SetPermission.revoked_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if grant is None:
        raise ApiError(404, "NOT_FOUND", "Разрешение не найдено.")
    grant.revoked_at = utcnow()
    await db.commit()
    return {"ok": True}
