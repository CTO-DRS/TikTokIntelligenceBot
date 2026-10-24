"""
Celery application — `celery -A bot.tasks worker --loglevel=info`

Periodic jobs (run `celery -A bot.tasks worker -B` to embed beat, or run a
dedicated `celery -A bot.tasks beat` process in production):

* every 10 min : tracked-account change checks → Telegram alerts
* hourly       : metric snapshots (30-day growth charts)
* every 6 h    : database backup with retention
* daily 03:00  : retention cleanup
* weekly       : usage digest to admins
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from celery import Celery
from celery.schedules import crontab

from bot.utils.logger import get_logger, setup_logging
from config.settings import get_settings

log = get_logger(__name__)
SETTINGS = get_settings()

celery_app = Celery(
    "tiktok_intel",
    broker=SETTINGS.get_redis_url(),
    backend=SETTINGS.get_redis_url(),
    include=["bot.tasks"],
)

celery_app.conf.update(
    timezone="UTC",
    enable_utc=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    worker_concurrency=4,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    beat_schedule={
        "check-tracked-every-10min": {
            "task": "bot.tasks.check_tracked_changes",
            "schedule": 600.0,
        },
        "snapshots-hourly": {
            "task": "bot.tasks.snapshot_watchlist",
            "schedule": crontab(minute=5),  # hourly at :05
        },
        "backup-every-6h": {
            "task": "bot.tasks.backup_database",
            "schedule": crontab(hour="*/6", minute=30),
        },
        "cleanup-daily": {
            "task": "bot.tasks.cleanup_old_data",
            "schedule": crontab(hour=3, minute=0),
        },
        "weekly-digest": {
            "task": "bot.tasks.weekly_digest",
            "schedule": crontab(hour=9, minute=0, day_of_week=6),
        },
    },
)


def _tg_send(token: str, chat_id: int, text: str) -> bool:
    """Direct Bot API call — works from worker processes without PTB runtime."""
    import requests

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        return resp.ok
    except Exception as exc:  # noqa: BLE001
        log.warning("tg_send failed: %s", exc)
        return False


def _run(coro_factory):
    """Bridge sync Celery tasks → async code (fresh event loop per task)."""
    return asyncio.run(coro_factory())


@celery_app.task(name="bot.tasks.check_tracked_changes", ignore_result=True)
def check_tracked_changes() -> int:
    setup_logging(SETTINGS.log_level)

    async def _inner():
        from bot.services.tracker import TrackingService
        from database.repository import Repository

        repo = Repository(SETTINGS)
        try:
            return await TrackingService(repo).check_all()
        finally:
            await repo.dispose()

    notifications = _run(_inner())
    for note in notifications:
        _tg_send(SETTINGS.bot_token, note["telegram_id"], note["text"])
    log.info("tracked-change task delivered %s alerts", len(notifications))
    return len(notifications)


@celery_app.task(name="bot.tasks.snapshot_watchlist", ignore_result=True)
def snapshot_watchlist() -> int:
    setup_logging(SETTINGS.log_level)

    async def _inner():
        from bot.services.tracker import TrackingService
        from database.repository import Repository

        repo = Repository(SETTINGS)
        try:
            service = TrackingService(repo)
            usernames = {r.tiktok_username for r in await repo.list_tracked(only_active=True)}
            done = 0
            for username in usernames:
                result = await service.client.fetch_profile(username, want_videos=3)
                if result.ok:
                    await service.take_snapshot(result.data)
                    done += 1
            return done
        finally:
            await repo.dispose()

    done = _run(_inner())
    log.info("snapshots taken: %s", done)
    return done


@celery_app.task(name="bot.tasks.backup_database", ignore_result=True)
def backup_database() -> str:
    setup_logging(SETTINGS.log_level)
    from scripts.backup import run_backup

    path = run_backup()
    log.info("backup created: %s", path)
    return str(path)


@celery_app.task(name="bot.tasks.cleanup_old_data", ignore_result=True)
def cleanup_old_data() -> dict:
    setup_logging(SETTINGS.log_level)
    from scripts.cleanup import run_cleanup

    scans, files = run_cleanup()
    return {"scans_deleted": scans, "files_deleted": files}


@celery_app.task(name="bot.tasks.weekly_digest", ignore_result=True)
def weekly_digest() -> int:
    setup_logging(SETTINGS.log_level)

    async def _inner():
        from database.repository import Repository

        repo = Repository(SETTINGS)
        try:
            return await repo.global_stats()
        finally:
            await repo.dispose()

    stats = _run(_inner())
    text = ("📊 <b>Weekly digest</b>\n" + json.dumps(
        {k: v for k, v in stats.items()}, ensure_ascii=False))
    sent = 0
    for admin_id in SETTINGS.admin_ids:
        if _tg_send(SETTINGS.bot_token, admin_id, text):
            sent += 1
    return sent
