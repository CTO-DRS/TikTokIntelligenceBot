"""
001_initial — initial schema.

The canonical schema lives in database/models.py; this module documents it and
provides raw-SQL DDL for DBAs who prefer applying SQL directly (e.g. inside a
managed pipeline where running Python is not allowed).
"""
from __future__ import annotations

DDL: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS tg_users (
        id SERIAL PRIMARY KEY,
        telegram_id BIGINT UNIQUE NOT NULL,
        username VARCHAR(64),
        first_name VARCHAR(128),
        language VARCHAR(5) NOT NULL DEFAULT 'ar',
        role VARCHAR(16) NOT NULL DEFAULT 'USER',
        detail_level VARCHAR(10) NOT NULL DEFAULT 'advanced',
        two_fa_secret VARCHAR(64),
        is_blocked BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS scan_records (
        id SERIAL PRIMARY KEY,
        telegram_user_id BIGINT NOT NULL REFERENCES tg_users(telegram_id) ON DELETE CASCADE,
        target_username VARCHAR(64) NOT NULL,
        scan_type VARCHAR(16) NOT NULL DEFAULT 'BASIC',
        status VARCHAR(16) NOT NULL DEFAULT 'OK',
        duration_ms INTEGER NOT NULL DEFAULT 0,
        result_path VARCHAR(512),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS ix_scan_records_tu ON scan_records (telegram_user_id);
    CREATE INDEX IF NOT EXISTS ix_scan_records_ca ON scan_records (created_at);
    """,
    """
    CREATE TABLE IF NOT EXISTS account_snapshots (
        id SERIAL PRIMARY KEY,
        tiktok_username VARCHAR(64) NOT NULL,
        followers BIGINT NOT NULL DEFAULT 0,
        following BIGINT NOT NULL DEFAULT 0,
        likes BIGINT NOT NULL DEFAULT 0,
        video_count INTEGER NOT NULL DEFAULT 0,
        views BIGINT NOT NULL DEFAULT 0,
        extras_json TEXT,
        captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS ix_snap_user_time ON account_snapshots (tiktok_username, captured_at);
    """,
    """
    CREATE TABLE IF NOT EXISTS tracked_accounts (
        id SERIAL PRIMARY KEY,
        telegram_user_id BIGINT NOT NULL REFERENCES tg_users(telegram_id) ON DELETE CASCADE,
        tiktok_username VARCHAR(64) NOT NULL,
        events_mask INTEGER NOT NULL DEFAULT 63,
        last_snapshot_id INTEGER REFERENCES account_snapshots(id) ON DELETE SET NULL,
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_track UNIQUE (telegram_user_id, tiktok_username)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS report_files (
        id SERIAL PRIMARY KEY,
        scan_id INTEGER REFERENCES scan_records(id) ON DELETE SET NULL,
        telegram_user_id BIGINT,
        kind VARCHAR(8) NOT NULL,
        path VARCHAR(512) NOT NULL,
        size_bytes INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_logs (
        id SERIAL PRIMARY KEY,
        actor_id BIGINT,
        action VARCHAR(64) NOT NULL,
        payload TEXT,
        ip VARCHAR(64),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS saved_profiles (
        id SERIAL PRIMARY KEY,
        telegram_user_id BIGINT NOT NULL REFERENCES tg_users(telegram_id) ON DELETE CASCADE,
        tiktok_username VARCHAR(64) NOT NULL,
        note VARCHAR(256),
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_saved UNIQUE (telegram_user_id, tiktok_username)
    );
    """,
]
