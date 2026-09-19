"""Импорт материала: preview со staging → подтверждение одной транзакцией."""
from __future__ import annotations

import csv
import hashlib
import io
import json

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import client_ip, get_current_user, get_db
from app.core.ratelimit import check_rate_limit
from app.core.config import settings
from app.core.errors import ApiError
from app.db.base import utcnow
import logging

from app.models import Card, Folder, FolderSet, ImportJob, SetModel, User
from app.services.access import get_set_access, require_owner
from app.services import sets_service
from app.services.quizlet_service import (
    extract_quizlet_title,
    fetch_quizlet_by_url,
    fetch_quizlet_folder_with_ezsolver,
    is_quizlet_folder_url,
    is_quizlet_url,
    parse_quizlet_text,
)
from app.schemas.sets import CardIn, SetCreate

logger = logging.getLogger("recall.imports")

router = APIRouter(prefix="/imports", tags=["imports"])

MAX_ERRORS_SHOWN = 50


def _decode(data: bytes, encoding: str) -> str:
    if encoding == "auto":
        for enc in ("utf-8-sig", "utf-8", "cp1251"):
            try:
                return data.decode(enc)
            except UnicodeDecodeError:
                continue
        raise ApiError(422, "ENCODING_ERROR", "Не удалось определить кодировку файла.")
    try:
        return data.decode(encoding)
    except (UnicodeDecodeError, LookupError):
        raise ApiError(422, "ENCODING_ERROR", f"Некорректная кодировка: {encoding}.")


def _normalize_row(raw: dict) -> dict:
    front = str(raw.get("front") or "").strip()
    back = str(raw.get("back") or "").strip()
    accepted_front = [a.strip() for a in str(raw.get("accepted_front") or "").split("|") if a.strip()]
    accepted_back = [a.strip() for a in str(raw.get("accepted_back") or "").split("|") if a.strip()]
    return {
        "front_text": front[:10000],
        "back_text": back[:10000],
        "front_context": str(raw.get("front_context") or "")[:500],
        "back_context": str(raw.get("back_context") or "")[:500],
        "front_hint": str(raw.get("front_hint") or "")[:500],
        "back_hint": str(raw.get("back_hint") or "")[:500],
        "front_explanation": str(raw.get("front_explanation") or "")[:5000],
        "back_explanation": str(raw.get("back_explanation") or "")[:5000],
        "front_example": str(raw.get("front_example") or "")[:2000],
        "back_example": str(raw.get("back_example") or "")[:2000],
        "accepted_front": accepted_front[:20],
        "accepted_back": accepted_back[:20],
    }


def parse_delimited(text: str, delimiter: str, has_header: str) -> list[dict]:
    sample = text[:2048]
    if delimiter == "auto":
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
            delim = dialect.delimiter
        except csv.Error:
            delim = "\t" if "\t" in sample else ","
    else:
        delim = {"comma": ",", "semicolon": ";", "tab": "\t", "pipe": "|"}[delimiter]
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    rows = [r for r in reader if any((c or "").strip() for c in r)]
    header = None
    if has_header == "true" or (has_header == "auto" and rows and _looks_like_header(rows[0])):
        header = [h.strip().lower() for h in rows[0]] if rows else None
        rows = rows[1:]
    out = []
    for i, r in enumerate(rows, start=2 if header else 1):
        raw = {}
        if header:
            for j, cell in enumerate(r):
                key = header[j] if j < len(header) else f"col{j}"
                raw[_map_key(key, j)] = cell
        else:
            raw["front"] = r[0] if len(r) > 0 else ""
            raw["back"] = r[1] if len(r) > 1 else ""
            if len(r) > 2:
                raw["accepted_back"] = r[2]
            if len(r) > 3:
                raw["front_hint"] = r[3]
            if len(r) > 4:
                raw["back_explanation"] = r[4]
        out.append({"line": i, **_normalize_row(raw)})
    return out


def _map_key(key: str, idx: int) -> str:
    aliases = {
        "front": "front", "термин": "front", "front_text": "front", "term": "front", "word": "front",
        "back": "back", "определение": "back", "back_text": "back", "definition": "back", "translation": "back", "перевод": "back",
        "accepted_front": "accepted_front", "accepted_back": "accepted_back", "aliases": "accepted_back",
        "hint": "front_hint", "подсказка": "front_hint",
        "explanation": "back_explanation", "пояснение": "back_explanation",
        "context": "front_context", "контекст": "front_context",
    }
    return aliases.get(key, key)


def _looks_like_header(row: list[str]) -> bool:
    if not row:
        return False
    first = (row[0] or "").strip().lower()
    return first in ("front", "term", "термин", "word", "front_text") or first in ("back", "definition", "определение")


def parse_json(text: str) -> list[dict]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ApiError(422, "PARSE_ERROR", f"Некорректный JSON: {e.msg} (строка {e.lineno}).")
    if not isinstance(data, list):
        raise ApiError(422, "PARSE_ERROR", "Ожидался JSON-массив карточек.")
    if len(data) > settings.max_import_rows:
        raise ApiError(413, "TOO_MANY_ROWS", f"Максимум строк импорта: {settings.max_import_rows}.")
    out = []
    for i, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            out.append({"line": i, "front_text": "", "back_text": "", "_error": "Элемент массива не объект."})
            continue
        raw = {
            "front": item.get("front", item.get("front_text", "")),
            "back": item.get("back", item.get("back_text", "")),
            "accepted_front": "|".join(item.get("accepted_front", item.get("accepted_answers", []) if isinstance(item.get("accepted_answers", []), list) else [])),
            "accepted_back": "|".join(item.get("accepted_back", [])),
            "front_context": item.get("front_context", item.get("context", "")),
            "back_context": item.get("back_context", ""),
            "front_hint": item.get("front_hint", item.get("hint", "")),
            "back_hint": item.get("back_hint", ""),
            "front_explanation": item.get("front_explanation", item.get("explanation", "")),
            "back_explanation": item.get("back_explanation", ""),
            "front_example": item.get("front_example", item.get("example", "")),
            "back_example": item.get("back_example", ""),
        }
        out.append({"line": i, **_normalize_row(raw)})
    return out


def validate_rows(rows: list[dict]) -> dict:
    valid = []
    errors = []
    seen: set[tuple[str, str]] = set()
    empty = 0
    duplicates = 0
    for r in rows:
        line = r.get("line", 0)
        if r.get("_error"):
            errors.append({"line": line, "message": r["_error"]})
            continue
        f_text = str(r.get("front_text") or "").strip()
        b_text = str(r.get("back_text") or "").strip()
        if not f_text and not b_text:
            empty += 1
            continue
        if not f_text or not b_text:
            errors.append({"line": line, "message": "Обе стороны карточки должны быть заполнены (или обе пустые ячейки = пропуск строки)."})
            continue
        key = (f_text.casefold(), b_text.casefold())
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        valid.append(r)
    return {"valid": valid, "errors": errors, "empty": empty, "duplicates_in_file": duplicates}


class ImportConfirm(BaseModel):
    job_id: str
    mode: str  # new | existing
    new_set: dict | None = None
    set_id: str | None = None
    duplicate_policy: str = "skip"  # skip | update | add
    expected_content_version: int = Field(default=1, ge=1)


class QuizletParseIn(BaseModel):
    text: str
    term_delimiter: str = "auto"
    card_delimiter: str = "auto"


@router.post("/quizlet/parse")
async def parse_quizlet_endpoint(
    payload: QuizletParseIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    check_rate_limit(f"quizlet:{user.id}:{client_ip(request)}", 10, 60)
    text = payload.text.strip()
    if not text:
        raise ApiError(422, "EMPTY_TEXT", "Вставьте текст или ссылку из Quizlet.")

    if is_quizlet_folder_url(text):
        folder_data = await fetch_quizlet_folder_with_ezsolver(text, download_cards=False, db=db)
        return {
            "ok": True,
            "is_folder": True,
            "folder_title": folder_data.get("folder_title", "Папка из Quizlet"),
            "total_sets": folder_data.get("total_sets", 0),
            "sets": folder_data.get("sets", []),
            "cards": [],
            "total_rows": 0,
            "valid_rows": 0,
            "empty_rows": 0,
            "duplicates_in_file": 0,
            "suggested_title": folder_data.get("folder_title", "Папка из Quizlet"),
            "suggested_front_lang": "",
            "suggested_back_lang": "",
        }

    suggested_title = ""
    suggested_front_lang = ""
    suggested_back_lang = ""

    if is_quizlet_url(text):
        data = await fetch_quizlet_by_url(text, db=db)
        rows = data.get("rows", [])
        suggested_title = data.get("title", "")
        suggested_front_lang = data.get("front_language", "")
        suggested_back_lang = data.get("back_language", "")
    else:
        rows = parse_quizlet_text(text, payload.term_delimiter, payload.card_delimiter)
        if not suggested_title:
            suggested_title = extract_quizlet_title(text)

    if not rows:
        raise ApiError(422, "NO_CARDS_PARSED", "Не удалось обнаружить карточки в тексте. Проверьте выбранные разделители.")

    result = validate_rows(rows)
    return {
        "ok": True,
        "is_folder": False,
        "total_rows": len(rows),
        "valid_rows": len(result["valid"]),
        "empty_rows": result["empty"],
        "duplicates_in_file": result["duplicates_in_file"],
        "cards": [
            {
                "front_text": r["front_text"],
                "back_text": r["back_text"],
                "front_hint": r.get("front_hint", ""),
                "back_hint": r.get("back_hint", ""),
            }
            for r in result["valid"]
        ],
        "suggested_title": suggested_title,
        "suggested_front_lang": suggested_front_lang,
        "suggested_back_lang": suggested_back_lang,
    }


class QuizletFolderPreviewIn(BaseModel):
    url: str


class QuizletFolderImportIn(BaseModel):
    url: str
    folder_name: str | None = None
    selected_set_ids: list[str] | None = None


@router.post("/quizlet/folder/preview")
async def quizlet_folder_preview(
    payload: QuizletFolderPreviewIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    check_rate_limit(f"quizlet:{user.id}:{client_ip(request)}", 10, 60)
    url = payload.url.strip()
    if not url:
        raise ApiError(422, "EMPTY_URL", "Укажите ссылку на папку или класс в Quizlet.")
    try:
        data = await fetch_quizlet_folder_with_ezsolver(url, download_cards=False, db=db)
        return {
            "ok": True,
            "folder_title": data.get("folder_title", "Папка из Quizlet"),
            "total_sets": data.get("total_sets", 0),
            "sets": data.get("sets", []),
        }
    except Exception as e:
        logger.exception("Failed to preview Quizlet folder")
        raise ApiError(400, "QUIZLET_FOLDER_ERROR", "Не удалось загрузить папку из Quizlet.") from e


@router.post("/quizlet/folder/import")
async def quizlet_folder_import(
    payload: QuizletFolderImportIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    check_rate_limit(f"quizlet:{user.id}:{client_ip(request)}", 10, 60)
    url = payload.url.strip()
    if not url:
        raise ApiError(422, "EMPTY_URL", "Укажите ссылку на папку или класс в Quizlet.")
    if payload.selected_set_ids and len(payload.selected_set_ids) > 100:
        raise ApiError(422, "TOO_MANY_SETS", "За один раз можно импортировать не более 100 наборов.")
    try:
        data = await fetch_quizlet_folder_with_ezsolver(
            url,
            download_cards=True,
            selected_set_ids=payload.selected_set_ids,
            db=db,
        )
    except Exception as e:
        logger.exception("Failed to download Quizlet folder sets")
        raise ApiError(400, "QUIZLET_FOLDER_ERROR", "Ошибка при загрузке наборов папки.") from e

    folder_name = (payload.folder_name or data.get("folder_title") or "Папка из Quizlet").strip()[:120]
    imported_sets = data.get("imported_sets", [])
    if not imported_sets:
        raise ApiError(422, "NO_SETS", "В папке не найдено доступных наборов для импорта.")

    # 1. Создаем или находим папку пользователя
    folder = (
        await db.execute(
            select(Folder).where(Folder.user_id == user.id, Folder.name == folder_name)
        )
    ).scalar_one_or_none()

    if not folder:
        folder = Folder(user_id=user.id, name=folder_name, created_by_admin=False)
        db.add(folder)
        await db.flush()

    # 2. Создаем наборы и привязываем к папке
    created_sets = []
    total_cards = 0

    for s_item in imported_sets:
        set_title = (s_item.get("title") or f"Набор {s_item['id']}").strip()[:300]
        cards_data = s_item.get("cards", [])
        card_ins = [
            CardIn(
                front_text=c.get("front_text", ""),
                back_text=c.get("back_text", ""),
            )
            for c in cards_data
            if c.get("front_text") or c.get("back_text")
        ]
        set_payload = SetCreate(
            title=set_title,
            description=f"Импортировано из Quizlet (ID: {s_item['id']})",
            front_language="",
            back_language="",
            tags=[],
            cards=card_ins,
        )
        st = await sets_service.create_set(db, user, set_payload)

        # Связываем с папкой
        fs_exists = (
            await db.execute(
                select(FolderSet).where(FolderSet.folder_id == folder.id, FolderSet.set_id == st.id)
            )
        ).scalar_one_or_none()
        if not fs_exists:
            db.add(FolderSet(folder_id=folder.id, set_id=st.id))

        created_sets.append({
            "id": st.id,
            "title": st.title,
            "card_count": len(card_ins),
        })
        total_cards += len(card_ins)

    await db.commit()
    return {
        "ok": True,
        "folder_id": folder.id,
        "folder_name": folder.name,
        "imported_sets_count": len(created_sets),
        "total_cards_count": total_cards,
        "sets": created_sets,
    }


@router.post("/preview")
async def preview(
    request: Request,
    file: UploadFile | None = File(default=None),
    text: str | None = Form(default=None),
    format: str = Form(default="auto"),
    delimiter: str = Form(default="auto"),
    encoding: str = Form(default="auto"),
    has_header: str = Form(default="auto"),
    term_delimiter: str = Form(default="auto"),
    card_delimiter: str = Form(default="auto"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    check_rate_limit(f"import:{user.id}:{client_ip(request)}", 20, 60)
    if file is not None:
        chunks = []
        total = 0
        while chunk := await file.read(1024 * 1024):
            total += len(chunk)
            if total > settings.max_import_bytes:
                raise ApiError(413, "FILE_TOO_LARGE", f"Максимальный размер файла импорта: {settings.max_import_bytes // (1024 * 1024)} MiB.")
            chunks.append(chunk)
        data = b"".join(chunks)
    elif text:
        data = text.encode("utf-8")
        if len(data) > settings.max_import_bytes:
            raise ApiError(413, "FILE_TOO_LARGE", f"Максимальный размер вставленного текста: {settings.max_import_bytes // (1024 * 1024)} MiB.")
    else:
        raise ApiError(422, "VALIDATION_ERROR", "Нужен файл или вставленный текст.")
    name = (file.filename if file else "pasted") or "pasted"
    fmt = format
    content = _decode(data, encoding)
    suggested_title = ""
    suggested_front_lang = ""
    suggested_back_lang = ""

    if is_quizlet_folder_url(content):
        folder_data = await fetch_quizlet_folder_with_ezsolver(content, download_cards=False, db=db)
        return {
            "job_id": "",
            "is_folder": True,
            "folder_title": folder_data.get("folder_title", "Папка из Quizlet"),
            "total_sets": folder_data.get("total_sets", 0),
            "sets": folder_data.get("sets", []),
            "format": "quizlet_folder",
            "suggested_title": folder_data.get("folder_title", "Папка из Quizlet"),
            "total_rows": 0,
            "valid_rows": 0,
            "empty_rows": 0,
            "duplicates_in_file": 0,
            "error_count": 0,
            "sample": [],
            "errors": [],
        }

    if fmt == "quizlet":
        if is_quizlet_url(content):
            quizlet_data = await fetch_quizlet_by_url(content, db=db)
            rows = quizlet_data.get("rows", [])
            suggested_title = quizlet_data.get("title", "")
            suggested_front_lang = quizlet_data.get("front_language", "")
            suggested_back_lang = quizlet_data.get("back_language", "")
        else:
            rows = parse_quizlet_text(content, term_delimiter, card_delimiter)
            if not suggested_title:
                suggested_title = extract_quizlet_title(content)
    elif fmt == "auto":
        lower = name.lower()
        if is_quizlet_url(content):
            quizlet_data = await fetch_quizlet_by_url(content, db=db)
            rows = quizlet_data.get("rows", [])
            suggested_title = quizlet_data.get("title", "")
            suggested_front_lang = quizlet_data.get("front_language", "")
            suggested_back_lang = quizlet_data.get("back_language", "")
            fmt = "quizlet"
        elif lower.endswith(".json") or (file is None and text and text.strip().startswith("[")):
            fmt = "json"
            rows = parse_json(content)
        elif lower.endswith(".tsv"):
            fmt = "tsv"
            rows = parse_delimited(content, "tab", has_header)
        elif file is None and text:
            # Check if quizlet format (tabs, dashes, alternating lines)
            quizlet_rows = parse_quizlet_text(content, term_delimiter, card_delimiter)
            if len(quizlet_rows) >= 1:
                rows = quizlet_rows
                fmt = "quizlet"
                if not suggested_title:
                    suggested_title = extract_quizlet_title(content)
            else:
                fmt = "csv"
                rows = parse_delimited(content, delimiter, has_header)
        else:
            fmt = "csv"
            rows = parse_delimited(content, delimiter, has_header)
    elif fmt == "json":
        rows = parse_json(content)
    elif fmt in ("csv", "tsv"):
        if fmt == "tsv" and delimiter == "auto":
            delimiter = "tab"
        rows = parse_delimited(content, delimiter, has_header)
    else:
        raise ApiError(422, "VALIDATION_ERROR", "Формат: quizlet, csv, tsv, json или text.")

    if len(rows) > settings.max_import_rows:
        raise ApiError(413, "TOO_MANY_ROWS", f"Максимум строк импорта: {settings.max_import_rows}.")
    result = validate_rows(rows)
    staging = json.dumps(result["valid"], ensure_ascii=False)
    job = ImportJob(
        user_id=user.id,
        status="ready",
        source_format=fmt,
        fingerprint=hashlib.sha256(staging.encode()).hexdigest(),
        preview_json=json.dumps(
            {
                "format": fmt,
                "total_rows": len(rows),
                "valid_rows": len(result["valid"]),
                "empty_rows": result["empty"],
                "duplicates_in_file": result["duplicates_in_file"],
                "error_count": len(result["errors"]),
                "sample": result["valid"][:5],
                "columns": sorted({k for r in result["valid"] for k in r.keys() if not k.startswith("_") and k != "line"}),
                "suggested_title": suggested_title,
                "suggested_front_lang": suggested_front_lang,
                "suggested_back_lang": suggested_back_lang,
            },
            ensure_ascii=False,
        ),
        staging_json=staging,
        errors_json=json.dumps(result["errors"][:MAX_ERRORS_SHOWN], ensure_ascii=False),
        finished_at=utcnow(),
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return {
        "job_id": job.id,
        **json.loads(job.preview_json),
        "errors": json.loads(job.errors_json),
    }


@router.post("")
async def confirm(
    payload: ImportConfirm,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    job = (
        await db.execute(select(ImportJob).where(ImportJob.id == payload.job_id, ImportJob.user_id == user.id))
    ).scalar_one_or_none()
    if job is None:
        raise ApiError(404, "NOT_FOUND", "Предпросмотр импорта не найден.")
    if job.status == "completed":
        return {"ok": True, "already_applied": True, "set_id": job.target_set_id}
    if job.status != "ready":
        raise ApiError(409, "JOB_NOT_READY", f"Предпросмотр в состоянии {job.status}.")
    rows = json.loads(job.staging_json)
    if not rows:
        raise ApiError(422, "EMPTY_IMPORT", "Нет пригодных строк для импорта.")
    duplicate_policy = payload.duplicate_policy
    if duplicate_policy not in ("skip", "update", "add"):
        raise ApiError(422, "VALIDATION_ERROR", "Политика дубликатов: skip, update или add.")

    if payload.mode == "new":
        spec = payload.new_set or {}
        title = str(spec.get("title") or "").strip()
        if not title:
            raise ApiError(422, "VALIDATION_ERROR", "Укажите название нового набора.")
        if len(rows) > settings.max_cards_per_set:
            raise ApiError(413, "TOO_MANY_CARDS", f"Максимум карточек в наборе: {settings.max_cards_per_set}.")
        from app.schemas.sets import SetCreate

        set_payload = SetCreate(
            title=title[:300],
            description=str(spec.get("description") or "")[:2000],
            front_language=str(spec.get("front_language") or "")[:16],
            back_language=str(spec.get("back_language") or "")[:16],
            tags=[str(t)[:64] for t in (spec.get("tags") or [])][:20],
            cards=[],
        )
        st = await sets_service.create_set(db, user, set_payload)
        applied = await _apply_rows(db, user, st, rows, duplicate_policy, from_position=0)
        job.target_set_id = st.id
    elif payload.mode == "existing":
        if not payload.set_id:
            raise ApiError(422, "VALIDATION_ERROR", "Укажите целевой набор.")
        st = await require_owner(db, user, payload.set_id)
        if st.content_version != payload.expected_content_version:
            raise ApiError(
                409, "SET_VERSION_CONFLICT", "Набор изменился; обновите предпросмотр.",
                {"current_content_version": st.content_version},
            )
        current = await sets_service.card_count(db, st.id)
        if current + len(rows) > settings.max_cards_per_set:
            raise ApiError(413, "TOO_MANY_CARDS", f"Превышен лимит карточек набора ({settings.max_cards_per_set}).")
        applied = await _apply_rows(db, user, st, rows, duplicate_policy, from_position=current)
        await sets_service.bump_set_version(db, st.id)
        job.target_set_id = st.id
    else:
        raise ApiError(422, "VALIDATION_ERROR", "Режим импорта: new или existing.")
    job.status = "completed"
    job.applied_at = utcnow()
    job.progress = 100
    await db.commit()
    return {"ok": True, "set_id": job.target_set_id, **applied}


async def _apply_rows(db: AsyncSession, user: User, st: SetModel, rows: list[dict], policy: str, from_position: int) -> dict:
    """Все валидированные карточки одной атомарной транзакцией (вызывающий код делает commit)."""
    existing = {
        (c.front_text.strip().casefold(), c.back_text.strip().casefold()): c
        for c in (
            await db.execute(select(Card).where(Card.set_id == st.id, Card.deleted_at.is_(None)))
        ).scalars().all()
    }
    pos = from_position
    added = updated = skipped = 0
    for r in rows:
        card_in = CardIn(
            front_text=str(r.get("front_text") or "").strip()[:10000],
            back_text=str(r.get("back_text") or "").strip()[:10000],
            front_context=str(r.get("front_context") or "")[:500],
            back_context=str(r.get("back_context") or "")[:500],
            front_hint=str(r.get("front_hint") or "")[:500],
            back_hint=str(r.get("back_hint") or "")[:500],
            front_explanation=str(r.get("front_explanation") or "")[:5000],
            back_explanation=str(r.get("back_explanation") or "")[:5000],
            front_example=str(r.get("front_example") or "")[:2000],
            back_example=str(r.get("back_example") or "")[:2000],
            accepted_front=list(r.get("accepted_front") or [])[:20],
            accepted_back=list(r.get("accepted_back") or [])[:20],
            front_language=r.get("front_language"),
            back_language=r.get("back_language"),
            enabled_front_to_back=bool(r.get("enabled_front_to_back", True)),
            enabled_back_to_front=bool(r.get("enabled_back_to_front", True)),
            written_check_front=bool(r.get("written_check_front", True)),
            written_check_back=bool(r.get("written_check_back", True)),
        )
        key = (card_in.front_text.casefold(), card_in.back_text.casefold())
        if key in existing:
            if policy == "skip":
                skipped += 1
                continue
            if policy == "update":
                from app.schemas.sets import CardPatch

                await sets_service_update(db, existing[key], CardPatch(**card_in.model_dump()))
                updated += 1
                continue
        await sets_service_create_card(db, st, card_in, pos)
        pos += 1
        added += 1
    return {"applied": added + updated, "added": added, "updated": updated, "skipped": skipped}


async def sets_service_create_card(db, st, card_in, pos):
    from app.services.cards_service import create_card

    return await create_card(db, st, card_in, at_position=pos)


async def sets_service_update(db, card, patch):
    from app.services.cards_service import apply_card_patch

    return await apply_card_patch(db, card, patch)


@router.get("/{job_id}")
async def job_status(
    job_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    job = (
        await db.execute(select(ImportJob).where(ImportJob.id == job_id, ImportJob.user_id == user.id))
    ).scalar_one_or_none()
    if job is None:
        raise ApiError(404, "NOT_FOUND", "Задание импорта не найдено.")
    return {
        "job_id": job.id,
        "status": job.status,
        "format": job.source_format,
        "target_set_id": job.target_set_id,
        "progress": job.progress,
        "created_at": job.created_at,
        "finished_at": job.finished_at,
        "applied_at": job.applied_at,
        **json.loads(job.preview_json),
    }


@router.get("/{job_id}/errors")
async def job_errors(
    job_id: str, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    job = (
        await db.execute(select(ImportJob).where(ImportJob.id == job_id, ImportJob.user_id == user.id))
    ).scalar_one_or_none()
    if job is None:
        raise ApiError(404, "NOT_FOUND", "Задание импорта не найдено.")
    return {"errors": json.loads(job.errors_json)}
