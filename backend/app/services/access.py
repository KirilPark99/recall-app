"""Матрица доступа к наборам. Применяется до пагинации и подсчёта результатов."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.models import SetPermission, SetModel, User


class Role(str, Enum):
    OWNER = "owner"
    READER = "reader"


@dataclass
class SetAccess:
    set: SetModel
    role: Role


def hidden_error() -> ApiError:
    # Одинаковый ответ для несуществующего и недоступного набора (защита от перебора).
    return ApiError(404, "NOT_FOUND", "Набор не найден или недоступен.")


def _visible_set_ids_subquery(user: User):
    from sqlalchemy import or_

    return (
        select(SetPermission.set_id)
        .where(SetPermission.user_id == user.id, SetPermission.revoked_at.is_(None))
    )


def visible_sets_condition(user: User, include_link: bool = False):
    """SQL-условие личной библиотеки наборов пользователя (без учёта soft-delete)."""
    if getattr(user, "role", None) == "admin":
        return SetModel.id.is_not(None)

    from sqlalchemy import or_

    return or_(
        SetModel.owner_id == user.id,
        SetModel.visibility == "server_public",
        SetModel.id.in_(_visible_set_ids_subquery(user)),
    )


async def get_set_access(
    db: AsyncSession, user: User, set_id: str, include_archived: bool = True
) -> SetAccess:
    st = (
        await db.execute(
            select(SetModel).where(SetModel.id == set_id, SetModel.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if st is None:
        raise hidden_error()
    if st.owner_id == user.id:
        if st.archived and not include_archived:
            raise hidden_error()
        return SetAccess(set=st, role=Role.OWNER)
    if st.visibility == "server_public":
        if st.archived and not include_archived:
            raise hidden_error()
        return SetAccess(set=st, role=Role.READER)
    grant = (
        await db.execute(
            select(SetPermission).where(
                SetPermission.set_id == set_id,
                SetPermission.user_id == user.id,
                SetPermission.revoked_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if grant is None:
        raise hidden_error()
    if st.archived and not include_archived:
        raise hidden_error()
    return SetAccess(set=st, role=Role.READER)


async def require_owner(db: AsyncSession, user: User, set_id: str) -> SetModel:
    st = (
        await db.execute(
            select(SetModel).where(SetModel.id == set_id, SetModel.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if st is None or st.owner_id != user.id:
        raise hidden_error()
    return st


async def get_card_access(db: AsyncSession, user: User, card_id: str) -> tuple[SetModel, Role]:
    """Доступ к карточке через её набор; вложенные ID проверяются вместе."""
    from sqlalchemy import select as _select

    from app.models import Card

    card = (
        await db.execute(_select(Card).where(Card.id == card_id, Card.deleted_at.is_(None)))
    ).scalar_one_or_none()
    if card is None:
        raise hidden_error()
    access = await get_set_access(db, user, card.set_id)
    return access.set, access.role
