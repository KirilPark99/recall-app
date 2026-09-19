"""Конфигурация приложения. Значения читаются из окружения/.env корня проекта."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "dev"
    app_base_url: str = "http://127.0.0.1:8000"
    cors_origins: str = ""
    data_dir: str = str(PROJECT_ROOT / "data")

    session_cookie_name: str = "recall_session"
    session_ttl_seconds: int = 14 * 24 * 3600
    pre_auth_ttl_seconds: int = 900

    rate_limit_login_attempts: int = 100
    rate_limit_login_window_seconds: int = 300
    rate_limit_redeem_per_window: int = 30
    trusted_proxy_ips: str = "127.0.0.1,::1"
    tts_cache_max_bytes: int = 512 * 1024 * 1024
    tts_cache_ttl_days: int = 30

    max_image_bytes: int = 8 * 1024 * 1024
    max_audio_bytes: int = 25 * 1024 * 1024
    max_import_bytes: int = 10 * 1024 * 1024
    max_zip_compressed_bytes: int = 100 * 1024 * 1024
    max_zip_uncompressed_bytes: int = 250 * 1024 * 1024
    max_cards_per_set: int = 5000
    max_import_rows: int = 5000
    page_default_size: int = 50
    page_max_size: int = 200
    max_test_questions: int = 100

    default_locale: str = "ru"
    allowed_locales: str = "ru,en"
    default_timezone: str = "Europe/Moscow"

    sqlite_synchronous: str = "FULL"
    sqlite_busy_timeout_ms: int = 5000

    cookie_secure: bool | None = None  # None → авто: True в production

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def use_secure_cookie(self) -> bool:
        return self.cookie_secure if self.cookie_secure is not None else self.is_production

    @property
    def allowed_locales_list(self) -> list[str]:
        return [x.strip() for x in self.allowed_locales.split(",") if x.strip()]

    @property
    def cors_origins_list(self) -> list[str]:
        origins = [x.strip() for x in self.cors_origins.split(",") if x.strip()]
        if self.app_env == "dev":
            dev_defaults = [
                "http://localhost:5173",
                "http://127.0.0.1:5173",
                "http://localhost:8000",
                "http://127.0.0.1:8000",
                "http://localhost:3000",
                "http://127.0.0.1:3000",
            ]
            for d in dev_defaults:
                if d not in origins:
                    origins.append(d)
        return origins

    @property
    def trusted_proxy_ips_set(self) -> set[str]:
        return {x.strip() for x in self.trusted_proxy_ips.split(",") if x.strip()}

    @property
    def database_path(self) -> Path:
        return self.data_dir_path / "app.sqlite3"

    @property
    def media_dir(self) -> Path:
        return self.data_dir_path / "media"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir_path / "backups"

    @property
    def tts_cache_dir(self) -> Path:
        return self.data_dir_path / "tts_cache"

    @property
    def data_dir_path(self) -> Path:
        p = Path(self.data_dir)
        return p if p.is_absolute() else (PROJECT_ROOT / p).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()


def ensure_dirs() -> None:
    settings.data_dir_path.mkdir(parents=True, exist_ok=True)
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    settings.backups_dir.mkdir(parents=True, exist_ok=True)
    settings.tts_cache_dir.mkdir(parents=True, exist_ok=True)
