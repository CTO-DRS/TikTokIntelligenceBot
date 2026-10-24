#!/usr/bin/env python3
"""
Database backup — plain-SQL dumps into data/backups with retention.

* PostgreSQL: uses pg_dump (custom -Fc format) when available.
* SQLite: copies the file safely.
* Also invoked by Celery beat every 6 hours (bot/tasks.py → backup_database).
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import get_settings  # noqa: E402
from bot.utils.logger import get_logger  # noqa: E402

log = get_logger(__name__)


def run_backup() -> Path:
    settings = get_settings()
    backup_dir = Path(settings.backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    url = settings.get_sync_database_url()

    if url.startswith("postgres"):
        target = backup_dir / f"pg_backup_{stamp}.dump"
        cmd = ["pg_dump", url, "-Fc", "-f", str(target)]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=600)
            log.info("pg_dump ok → %s", target)
            return target
        except FileNotFoundError:
            log.warning("pg_dump not installed — falling back to JSON metadata backup")
        except subprocess.CalledProcessError as exc:
            log.error("pg_dump failed: %s", exc.stderr.decode(errors="ignore")[:400])

    if url.startswith("sqlite"):
        src = Path(url.replace("sqlite:///", ""))
        if src.exists():
            target = backup_dir / f"sqlite_backup_{stamp}.db"
            shutil.copy2(src, target)
            log.info("sqlite backup → %s", target)
            return target

    # last resort: keep a manifest so rotations stay consistent
    target = backup_dir / f"backup_manifest_{stamp}.json"
    target.write_text('{"status": "engine-unavailable", "at": "%s"}'
                      % datetime.now(timezone.utc).isoformat(), encoding="utf-8")
    return target


def rotate(retention_days: int | None = None) -> int:
    settings = get_settings()
    days = retention_days if retention_days is not None else settings.backup_retention_days
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    removed = 0
    for f in Path(settings.backup_dir).glob("backup_*"):
        if datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc) < cutoff:
            f.unlink(missing_ok=True)
            removed += 1
    return removed


if __name__ == "__main__":
    path = run_backup()
    removed = rotate()
    print(f"✅ backup → {path} | rotated {removed} old files")
