"""Каталог общих наборов сервера."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models import SetModel, User
from app.services import sets_service
from app.services.access import visible_sets_condition

router = APIRouter(prefix="/discover", tags=["discover"])


@router.get("/sets")
async def discover_sets(
    q: str | None = Query(default=None, max_length=200),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    conds = [
        SetModel.visibility == "server_public",
        SetModel.deleted_at.is_(None),
        SetModel.archived.is_(False),
        SetModel.owner_id != user.id,  # свои наборы видны в «Моих наборах»
    ]
    if q:
        from app.services import search as search_index

        ids = await search_index.search_set_ids(db, q, None)
        if not ids:
            return {"items": [], "total": 0}
        conds.append(SetModel.id.in_(ids))
    base = select(SetModel.id).where(*conds)
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (
        await db.execute(base.order_by(SetModel.updated_at.desc()).offset((page - 1) * page_size).limit(page_size))
    ).scalars().all()
    items = await sets_service.get_set_list_items(db, user, list(rows), "discover")
    return {"items": items, "total": total, "page": page}
