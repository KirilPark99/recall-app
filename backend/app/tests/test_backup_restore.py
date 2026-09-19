import sqlite3

from click.testing import CliRunner

from app.cli import cli
from app.cli_backup import create_backup, verify_backup
from app.core.config import settings


def test_backup_restores_nested_media_atomically(tmp_path):
    data = tmp_path / "data"
    media = data / "media" / "ab"
    media.mkdir(parents=True)
    media_file = media / "nested.bin"
    media_file.write_bytes(b"nested-media")
    db_path = data / "app.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE media(storage_key TEXT, deleted_at TEXT);
        INSERT INTO media VALUES ('ab/nested.bin', NULL);
        CREATE TABLE sessions(revoked_at TEXT);
        CREATE TABLE share_links(revoked_at TEXT);
        CREATE TABLE set_permissions(source TEXT, revoked_at TEXT);
        CREATE TABLE import_jobs(status TEXT);
        """
    )
    conn.commit()
    conn.close()
    archive = tmp_path / "backup.tar.gz"
    original_data_dir = settings.data_dir
    settings.data_dir = str(data)
    try:
        create_backup(archive)
        assert verify_backup(archive)["media_invalid"] == []
        media_file.unlink()
        result = CliRunner().invoke(cli, ["backup", "restore", str(archive), "--confirm"])
        assert result.exit_code == 0, result.output
        assert media_file.read_bytes() == b"nested-media"
        assert not (data / "manifest.json").exists()
    finally:
        settings.data_dir = original_data_dir
