"""Backup и maintenance CLI-команды (SQLite backup API)."""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import sqlite3
import sys
import tarfile
import tempfile
import shutil
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import click

BACKUP_FORMAT_VERSION = 2


def _copy_db_via_backup_api(source: Path, target: Path) -> None:
    """Согласованная копия через sqlite3 backup API (не файловое копирование)."""
    src = sqlite3.connect(str(source))
    dst = sqlite3.connect(str(target))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def _strip_sessions(conn: sqlite3.Connection) -> None:
    """Временная копия не содержит активных login/CSRF-сессий."""
    conn.execute("UPDATE sessions SET revoked_at = strftime('%Y-%m-%dT%H:%M:%f','now') WHERE revoked_at IS NULL")
    conn.commit()


def _manifest(db_path: Path, media_files: list[tuple[str, int, str]]) -> dict:
    return {
        "app": "Recall",
        "backup_format_version": BACKUP_FORMAT_VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "database": {"name": "app.sqlite3", "size": db_path.stat().st_size, "sha256": _sha256(db_path)},
        "media": [{"storage_key": k, "size": s, "sha256": h} for k, s, h in media_files],
    }


def _collect_media(media_dir: Path, snapshot_conn: sqlite3.Connection) -> list[tuple[str, int, str]]:
    rows = snapshot_conn.execute(
        "SELECT storage_key FROM media WHERE deleted_at IS NULL"
    ).fetchall()
    out = []
    for (storage_key,) in rows:
        p = (media_dir / storage_key).resolve()
        if not p.is_relative_to(media_dir.resolve()):
            raise click.ClickException(f"Опасный storage_key в базе: {storage_key}")
        if not p.is_file():
            raise click.ClickException(f"Отсутствует media-файл из базы: {storage_key}")
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        out.append((storage_key, p.stat().st_size, h.hexdigest()))
    return out


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_backup(output: Path) -> Path:
    from app.core.config import settings

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        db_copy = tmp_path / "app.sqlite3"
        _copy_db_via_backup_api(settings.database_path, db_copy)
        conn = sqlite3.connect(str(db_copy))
        try:
            _strip_sessions(conn)
            media_files = _collect_media(settings.media_dir, conn)
        finally:
            conn.close()
        manifest = _manifest(db_copy, media_files)
        with tarfile.open(output, "w:gz") as tar:
            tar.add(db_copy, arcname="app.sqlite3")
            media_dir = settings.media_dir
            for key, _size, _h in media_files:
                p = media_dir / key
                tar.add(p, arcname=f"media/{key}")
            manifest_path = tmp_path / "manifest.json"
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            tar.add(manifest_path, arcname="manifest.json")
    os.chmod(output, 0o600)
    return output


def verify_backup(path: Path) -> dict:
    """Проверка формата, целостности базы и наличия файлов манифеста."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        with tarfile.open(path, "r:gz") as tar:
            _safe_extract(tar, tmp_path)
        manifest_path = tmp_path / "manifest.json"
        if not manifest_path.is_file():
            raise click.ClickException("В архиве нет manifest.json — это не backup Recall.")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("app") != "Recall":
            raise click.ClickException("Неизвестный формат backup.")
        if manifest.get("backup_format_version") != BACKUP_FORMAT_VERSION:
            raise click.ClickException("Неподдерживаемая версия формата backup.")
        db_path = tmp_path / "app.sqlite3"
        if not db_path.is_file():
            raise click.ClickException("В архиве нет базы данных.")
        expected_db_size = manifest.get("database", {}).get("size")
        if expected_db_size != db_path.stat().st_size:
            raise click.ClickException("Размер базы не совпадает с manifest.")
        if manifest.get("database", {}).get("sha256") != _sha256(db_path):
            raise click.ClickException("Хэш базы не совпадает с manifest.")
        conn = sqlite3.connect(str(db_path))
        try:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            fk_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
        finally:
            conn.close()
        missing = []
        invalid = []
        media_dir = tmp_path / "media"
        media_manifest = manifest.get("media", [])
        if not isinstance(media_manifest, list) or not all(isinstance(item, dict) for item in media_manifest):
            raise click.ClickException("Некорректный media manifest.")
        expected_media = {item.get("storage_key", "") for item in media_manifest}
        if len(expected_media) != len(media_manifest):
            raise click.ClickException("Manifest содержит повторяющиеся media storage_key.")
        for item in media_manifest:
            key = item.get("storage_key", "")
            media_path = (media_dir / key).resolve()
            if not key or not media_path.is_relative_to(media_dir.resolve()):
                raise click.ClickException(f"Опасный storage_key в manifest: {key}")
            if not media_path.is_file():
                missing.append(key)
                continue
            actual_hash = _sha256(media_path)
            if media_path.stat().st_size != item.get("size") or actual_hash != item.get("sha256"):
                invalid.append(key)
        if media_dir.exists():
            actual_media = {str(path.relative_to(media_dir)) for path in media_dir.rglob("*") if path.is_file()}
            invalid.extend(f"unexpected:{key}" for key in sorted(actual_media - expected_media))
        return {
            "format_version": manifest.get("backup_format_version"),
            "created_at": manifest.get("created_at_utc"),
            "integrity_check": integrity,
            "foreign_key_errors": len(fk_errors),
            "media_files": len(manifest.get("media", [])),
            "media_missing": missing,
            "media_invalid": invalid,
        }


def _safe_extract(tar: tarfile.TarFile, dest: Path) -> None:
    """Распаковка с защитой от path traversal и symlink."""
    dest = dest.resolve()
    for member in tar.getmembers():
        target = (dest / member.name).resolve()
        if not target.is_relative_to(dest):
            raise click.ClickException(f"Опасный путь в архиве: {member.name}")
        if member.issym() or member.islnk():
            raise click.ClickException(f"Ссылки в архиве не поддерживаются: {member.name}")
    tar.extractall(dest, filter="data")


def register_backup_commands(cli) -> None:
    @cli.group()
    def backup() -> None:
        """Резервное копирование и восстановление."""

    @backup.command()
    @click.option("--output", "output", required=True, type=click.Path(path_type=Path))
    def create(output: Path) -> None:
        """Создать согласованный backup (SQLite backup API + медиа + manifest)."""
        path = create_backup(output)
        click.echo(f"Backup создан: {path} ({path.stat().st_size} байт)")

    @backup.command()
    @click.argument("path", type=click.Path(exists=True, path_type=Path))
    def verify(path: Path) -> None:
        """Проверить backup без восстановления."""
        report = verify_backup(path)
        click.echo(json.dumps(report, ensure_ascii=False, indent=2))
        if (
            report["integrity_check"] != "ok"
            or report["foreign_key_errors"]
            or report["media_missing"]
            or report["media_invalid"]
        ):
            sys.exit(1)

    @backup.command()
    @click.argument("path", type=click.Path(exists=True, path_type=Path))
    @click.option("--confirm", is_flag=True)
    def restore(path: Path, confirm: bool) -> None:
        """Восстановление: останавливает приложение, заменяет DATA_DIR (старый каталог сохраняется)."""
        from app.core.config import settings

        if not confirm:
            raise click.ClickException("Укажите --confirm для подтверждения замены данных.")
        report = verify_backup(path)
        if (
            report["integrity_check"] != "ok"
            or report["foreign_key_errors"]
            or report["media_missing"]
            or report["media_invalid"]
        ):
            raise click.ClickException("Backup повреждён; восстановление прервано.")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        data_dir = settings.data_dir_path
        rollback = data_dir.parent / f"data.rollback-{stamp}"
        data_dir.parent.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=".recall-restore-", dir=data_dir.parent))
        moved_old = False
        try:
            with tarfile.open(path, "r:gz") as tar:
                _safe_extract(tar, stage)
            (stage / "manifest.json").unlink()
            (stage / "media").mkdir(exist_ok=True)
            (stage / "backups").mkdir(exist_ok=True)
            (stage / "tts_cache").mkdir(exist_ok=True)
            # Старые сессии/ссылки не должны вновь давать доступ.
            conn = sqlite3.connect(str(stage / "app.sqlite3"))
            try:
                conn.execute("PRAGMA foreign_keys=ON")
                conn.execute("UPDATE sessions SET revoked_at = strftime('%Y-%m-%dT%H:%M:%f','now') WHERE revoked_at IS NULL")
                conn.execute("UPDATE share_links SET revoked_at = strftime('%Y-%m-%dT%H:%M:%f','now') WHERE revoked_at IS NULL")
                conn.execute("UPDATE set_permissions SET revoked_at = strftime('%Y-%m-%dT%H:%M:%f','now') WHERE source = 'share_link' AND revoked_at IS NULL")
                conn.execute("UPDATE import_jobs SET status='interrupted' WHERE status IN ('preview','ready')")
                conn.commit()
                if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise click.ClickException("Восстановленная база не прошла integrity_check.")
                if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
                    raise click.ClickException("Восстановленная база содержит ошибки внешних ключей.")
            finally:
                conn.close()
            if data_dir.exists():
                if rollback.exists():
                    raise click.ClickException(f"Каталог отката уже существует: {rollback}")
                data_dir.rename(rollback)
                moved_old = True
            stage.rename(data_dir)
            click.echo(f"Восстановление завершено. Прежний каталог сохранён: {rollback}")
        except Exception:
            if moved_old and rollback.exists() and not data_dir.exists():
                rollback.rename(data_dir)
            raise
        finally:
            if stage.exists():
                shutil.rmtree(stage)

    @cli.group()
    def maintenance() -> None:
        """Обслуживание."""

    @maintenance.command("cleanup-sessions")
    def cleanup_sessions() -> None:
        """Удалить истёкшие и отозванные сессии."""
        from app.core.db import get_sessionmaker
        from app.models import Session

        async def run():
            from sqlalchemy import delete

            from app.db.base import utcnow

            async with get_sessionmaker()() as db:
                res = await db.execute(
                    delete(Session).where(
                        (Session.expires_at < utcnow()) | (Session.revoked_at.is_not(None))
                    )
                )
                await db.commit()
                click.echo(f"Удалено сессий: {res.rowcount}")

        asyncio.run(run())

    @maintenance.command("cleanup-media")
    @click.option("--dry-run", is_flag=True)
    def cleanup_media(dry_run: bool) -> None:
        """Найти (и при --no-dry-run удалить) медиа без действующих ссылок."""
        from app.core.db import get_sessionmaker

        async def run():
            from sqlalchemy import select

            from app.core.config import settings
            from app.models import CardMedia, Media, SnapshotMedia

            async with get_sessionmaker()() as db:
                rows = (await db.execute(select(Media).where(Media.deleted_at.is_(None)))).scalars().all()
                used_cards = set((await db.execute(select(CardMedia.media_id))).scalars())
                used_snaps = set((await db.execute(select(SnapshotMedia.media_id))).scalars())
                orphans = [m for m in rows if m.id not in used_cards and m.id not in used_snaps]
                click.echo(f"Медиа без ссылок: {len(orphans)}")
                if not dry_run:
                    import os as _os

                    from app.db.base import utcnow

                    for m in orphans:
                        m.deleted_at = utcnow()
                        fp = settings.media_dir / m.storage_key
                        if fp.is_file():
                            fp.unlink()
                    await db.commit()
                    click.echo("Помечены удалёнными, файлы удалены.")
                else:
                    for m in orphans:
                        click.echo(f"  {m.storage_key}")

        asyncio.run(run())

    @maintenance.command("sqlite-checkpoint")
    def sqlite_checkpoint() -> None:
        """Ручной WAL-checkpoint."""
        from app.core.config import settings

        conn = sqlite3.connect(str(settings.database_path))
        try:
            result = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            click.echo(f"Checkpoint: busy={result[0]}, wal_frames={result[1]}, checkpointed={result[2]}")
        finally:
            conn.close()

    @maintenance.command("cleanup-tts")
    def cleanup_tts() -> None:
        """Удалить просроченный TTS-кэш и применить лимит размера."""
        from app.services.tts_service import cleanup_tts_cache

        click.echo(f"Удалено TTS-файлов: {cleanup_tts_cache()}")
