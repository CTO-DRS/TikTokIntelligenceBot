"""
Central application settings.

Every tunable value is loaded from environment variables or a `.env` file
(root `.env` or `docker/.env`).  Secrets NEVER live in the code base.
"""
from __future__ import annotations

import base64
import os
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(BASE_DIR / ".env"), str(BASE_DIR / "docker" / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Telegram ──────────────────────────────────────────────
    bot_token: str = ""
    admin_user_ids: str = ""          # comma separated telegram ids
    webhook_url: str = ""             # e.g. https://bot.example.com (empty → polling)
    webhook_port: int = 8080
    webhook_secret: str = ""

    # ── Database ──────────────────────────────────────────────
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "tiktok"
    postgres_password: str = "tiktok_secret"
    postgres_db: str = "tiktok_intel"
    database_url: str = ""            # full URL overrides the pg_* fields

    # ── Redis / Celery ────────────────────────────────────────
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_url: str = ""

    # ── Security ──────────────────────────────────────────────
    encryption_key: str = ""          # base64 of 32 random bytes (AES-256)
    rate_limit_scan_hour: int = 15
    rate_limit_deep_hour: int = 5
    rate_limit_bulk_hour: int = 2
    rate_limit_report_hour: int = 8
    rate_limit_global_minute: int = 20
    two_fa_enabled: bool = False

    # ── TikTok collector ──────────────────────────────────────
    tiktok_sessionid: str = ""        # optional cookie, improves stability
    scraping_timeout: int = 25
    scraping_retries: int = 3
    scraping_proxy: str = ""          # optional http(s) proxy URL
    demo_fallback: bool = True        # serve clearly-labelled demo data if blocked
    videos_deep_count: int = 30

    # ── Retention / storage ───────────────────────────────────
    scan_retention_days: int = 30
    snapshot_retention_days: int = 180
    backup_retention_days: int = 14
    backup_dir: str = str(BASE_DIR / "data" / "backups")
    report_dir: str = str(BASE_DIR / "data" / "reports")

    # ── Monitoring ────────────────────────────────────────────
    sentry_dsn: str = ""
    metrics_enabled: bool = True
    metrics_port: int = 9091
    log_level: str = "INFO"

    # ── Defaults ──────────────────────────────────────────────
    default_language: str = "ar"

    @field_validator("default_language")
    @classmethod
    def _valid_lang(cls, v: str) -> str:
        v = (v or "ar").lower()
        return v if v in {"ar", "en"} else "ar"

    # ── helpers ───────────────────────────────────────────────
    @property
    def admin_ids(self) -> list[int]:
        raw = (self.admin_user_ids or "").replace(" ", "")
        return [int(x) for x in raw.split(",") if x.strip().isdigit()]

    def get_database_url(self) -> str:
        """Async SQLAlchemy URL. Falls back to SQLite for zero-config local dev."""
        if self.database_url:
            return self.database_url
        if os.environ.get("POSTGRES_HOST"):
            return (
                f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
                f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
            )
        return f"sqlite+aiosqlite:///{BASE_DIR / 'data' / 'bot.db'}"

    def get_sync_database_url(self) -> str:
        url = self.get_database_url()
        return (
            url.replace("postgresql+asyncpg://", "postgresql://")
            .replace("sqlite+aiosqlite://", "sqlite:///")
        )

    def get_redis_url(self) -> str:
        if self.redis_url:
            return self.redis_url
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    def ensure_dirs(self) -> None:
        Path(BASE_DIR / "data").mkdir(parents=True, exist_ok=True)
        Path(self.backup_dir).mkdir(parents=True, exist_ok=True)
        Path(self.report_dir).mkdir(parents=True, exist_ok=True)

    @staticmethod
    def generate_encryption_key() -> str:
        """Print a fresh AES-256 key: python -c 'from config.settings import Settings;print(Settings.generate_encryption_key())'"""
        return base64.b64encode(os.urandom(32)).decode()


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
