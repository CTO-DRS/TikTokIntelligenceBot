#!/usr/bin/env python3
"""
Schema migration — `python scripts/migrate.py [--drop]`

Creates all tables from database/models.py (SQLAlchemy metadata). Works with
PostgreSQL (docker) or SQLite (zero-config local dev).
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import get_settings  # noqa: E402
from database.migrations.initial_001 import DDL  # noqa: E402,F401  (documentation import)
from database.repository import Repository  # noqa: E402


async def main(drop: bool = False) -> None:
    settings = get_settings()
    print(f"→ database: {settings.get_database_url().split('@')[-1]}")
    repo = Repository(settings)
    try:
        await repo.init_models(drop=drop)
        print("✅ migration complete — all tables are ready")
        print("   tg_users | scan_records | tracked_accounts | account_snapshots")
        print("   report_files | audit_logs | saved_profiles")
    finally:
        await repo.dispose()


if __name__ == "__main__":
    asyncio.run(main(drop="--drop" in sys.argv))
