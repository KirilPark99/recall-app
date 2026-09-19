"""Логика share-ссылок (используется API и сменой режима доступа)."""
from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utcnow
from app.models import SetModel, SetPermission, ShareLink


async def _revoke_link(db: AsyncSession, link: ShareLink) -> None:
    link.revoked_at = utcnow()
    await db.execute(
        update(SetPermission)
        .where(SetPermission.share_link_id == link.id, SetPermission.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )


async def revoke_links_on_privatize(db: AsyncSession, st: SetModel) -> None:
    """Набор стал «Личным»: ссылки отзываются вместе с производными разрешениями."""
    links = (
        await db.execute(
            select(ShareLink).where(ShareLink.set_id == st.id, ShareLink.revoked_at.is_(None))
        )
    ).scalars().all()
    for link in links:
        await _revoke_link(db, link)
