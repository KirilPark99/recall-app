"""Экспорт набора: JSON (полный перенос), CSV/TSV, ZIP с медиа, «для таблиц»."""
from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.config import settings
from app.core.errors import ApiError
from app.models import Card, Media, SetModel, SetTag, Tag, User
from app.services.access import get_set_access
from app.services.card_dto import load_set_cards

router = APIRouter(tags=["exports"])

SCHEMA_VERSION = 1
CSV_COLUMNS = [
    "front", "back", "front_context", "back_context", "front_hint", "back_hint",
    "front_explanation", "back_explanation", "front_example", "back_example",
    "accepted_front", "accepted_back", "front_language", "back_language",
]


def _card_dict(card: Card, acc_front: list[str], acc_back: list[str]) -> dict:
    return {
        "id": card.id,
        "position": card.position,
        "front_text": card.front_text,
        "back_text": card.back_text,
        "front_context": card.front_context,
        "back_context": card.back_context,
        "front_hint": card.front_hint,
        "back_hint": card.back_hint,
        "front_explanation": card.front_explanation,
        "back_explanation": card.back_explanation,
        "front_example": card.front_example,
        "back_example": card.back_example,
        "front_language": card.front_language,
        "back_language": card.back_language,
        "enabled_front_to_back": card.enabled_front_to_back,
        "enabled_back_to_front": card.enabled_back_to_front,
        "written_check_front": card.written_check_front,
        "written_check_back": card.written_check_back,
        "accepted_front": acc_front,
        "accepted_back": acc_back,
    }


async def _export_data(db: AsyncSession, st: SetModel) -> dict:
    cards = await load_set_cards(db, st.id)
    tags = (
        await db.execute(select(Tag.name).join(SetTag, SetTag.tag_id == Tag.id).where(SetTag.set_id == st.id))
    ).scalars().all()
    return {
        "schema_version": SCHEMA_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "app": "Recall",
        "set": {
            "title": st.title,
            "description": st.description,
            "front_language": st.front_language,
            "back_language": st.back_language,
            "tags": list(tags),
        },
        "cards": [
            _card_dict(
                c,
                [a.answer for a in sorted((a for a in c.accepted_answers if a.side == "front"), key=lambda a: a.position)],
                [a.answer for a in sorted((a for a in c.accepted_answers if a.side == "back"), key=lambda a: a.position)],
            )
            for c in cards
        ],
    }


def _safe_cell(value: str) -> str:
    """Защита от formula injection для экспорта «для таблиц»."""
    if value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _delimited(data: dict, delimiter: str, table_safe: bool) -> str:
    out = io.StringIO()
    writer = csv.writer(out, delimiter=delimiter, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(CSV_COLUMNS)
    for c in data["cards"]:
        row = [
            c["front_text"], c["back_text"], c["front_context"], c["back_context"],
            c["front_hint"], c["back_hint"], c["front_explanation"], c["back_explanation"],
            c["front_example"], c["back_example"],
            "|".join(c["accepted_front"]), "|".join(c["accepted_back"]),
            c["front_language"] or data["set"]["front_language"],
            c["back_language"] or data["set"]["back_language"],
        ]
        if table_safe:
            row = [_safe_cell(str(x)) for x in row]
        writer.writerow(row)
    return out.getvalue()


@router.get("/sets/{set_id}/export")
async def export_set(
    set_id: str,
    format: str = "json",
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    access = await get_set_access(db, user, set_id)
    st = access.set
    data = await _export_data(db, st)
    safe_title = "".join(ch for ch in st.title if ch.isalnum() or ch in " -_")[:60] or "set"

    if format == "json":
        return Response(
            content=json.dumps(data, ensure_ascii=False, indent=1),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{safe_title}.json"'},
        )
    if format in ("csv", "tsv"):
        delim = "," if format == "csv" else "\t"
        body = _delimited(data, delim, table_safe=False)
        media_type = "text/csv" if format == "csv" else "text/tab-separated-values"
        return Response(
            content="\ufeff" + body,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{safe_title}.{format}"'},
        )
    if format == "table":
        body = _delimited(data, "\t", table_safe=True)
        return Response(
            content="\ufeff" + body,
            media_type="text/tab-separated-values",
            headers={"Content-Disposition": f'attachment; filename="{safe_title}-table.tsv"'},
        )
    if format == "zip":
        buffer = io.BytesIO()
        media_by_key: dict[str, Media] = {}
        card_ids = [c["id"] for c in data["cards"]]
        if card_ids:
            from app.models import CardMedia

            rows = (
                await db.execute(
                    select(CardMedia, Media)
                    .join(Media, Media.id == CardMedia.media_id)
                    .where(CardMedia.card_id.in_(card_ids), Media.deleted_at.is_(None))
                )
            ).all()
            media_refs = []
            for cm, m in rows:
                media_refs.append({"card_id": cm.card_id, "side": cm.side, "media_key": m.storage_key, "position": cm.position})
                media_by_key[m.storage_key] = m
            data["media"] = media_refs
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps(
                {"app": "Recall", "kind": "set-export", "schema_version": SCHEMA_VERSION,
                 "created_at": data["exported_at"], "files": ["cards.json"] + [f"media/{k}" for k in media_by_key]},
                ensure_ascii=False, indent=1), "utf-8")
            zf.writestr("cards.json", json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
            for key, m in media_by_key.items():
                path = settings.media_dir / key
                if path.is_file():
                    zf.write(path, f"media/{key}")
        return Response(
            content=buffer.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{safe_title}.zip"'},
        )
    raise ApiError(422, "VALIDATION_ERROR", "Формат экспорта: json, csv, tsv, table или zip.")
