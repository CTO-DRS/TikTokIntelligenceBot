#!/usr/bin/env python3
"""
Retention cleanup — `python scripts/cleanup.py`

Deletes expired scan records, snapshots and generated report files.
Returns (scans_deleted, files_deleted); also invoked daily by Celery beat.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import get_settings  # noqa: E402


def run_cleanup() -> tuple[int, int]:
    settings = get_settings()

    async def _purge() -> int:
        from database.repository import Repository

        repo = Repository(settings)
        try:
            return await repo.cleanup(settings.scan_retention_days,
                                      settings.snapshot_retention_days)
        finally:
            await repo.dispose()

    scans_deleted = asyncio.run(_purge())

    files_deleted = 0
    report_dir = Path(settings.report_dir)
    if report_dir.exists():
        for f in report_dir.glob("report_*"):
            age_days = f.stat().st_mtime
            import time

            if (time.time() - age_days) > settings.scan_retention_days * 86400:
                f.unlink(missing_ok=True)
                files_deleted += 1
    return scans_deleted, files_deleted


if __name__ == "__main__":
    scans, files = run_cleanup()
    print(f"🧹 cleaned {scans} scan rows and {files} old report files")
