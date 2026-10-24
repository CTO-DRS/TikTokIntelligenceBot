"""
Application entry point — python bot/main.py

* Polling by default; set WEBHOOK_URL to switch to webhook mode (behind Nginx).
* Registers all 17 commands, the callback router, the text router and an
  error handler; starts an in-process tracking job and a Prometheus exporter.
"""
from __future__ import annotations

import asyncio

from telegram import BotCommand
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from bot.handlers import callbacks, commands, messages
from bot.utils.i18n import t
from bot.utils.logger import get_logger, setup_logging
from config.settings import get_settings
from database.repository import get_repository

log = get_logger(__name__)
SETTINGS = get_settings()

COMMAND_DESCRIPTIONS = [
    BotCommand("start", "القائمة الرئيسية / Main menu"),
    BotCommand("scan", "فحص حساب / Scan an account"),
    BotCommand("deepscan", "فحص عميق / Deep scan"),
    BotCommand("bulk", "فحص جماعي / Bulk scan"),
    BotCommand("compare", "مقارنة حسابين / Compare two accounts"),
    BotCommand("track", "تتبع حساب / Track an account"),
    BotCommand("stats", "إحصائياتك / Your stats"),
    BotCommand("report", "تقرير pdf html xlsx json / Generate report"),
    BotCommand("history", "سجل الفحوصات / Scan history"),
    BotCommand("settings", "الإعدادات / Settings"),
    BotCommand("export", "تصدير بياناتك / Export your data"),
    BotCommand("admin", "لوحة المشرف / Admin panel"),
    BotCommand("broadcast", "رسالة جماعية (مشرف) / Broadcast (admin)"),
    BotCommand("block", "حظر (مشرف) / Block (admin)"),
    BotCommand("unblock", "رفع الحظر (مشرف) / Unblock (admin)"),
    BotCommand("stats_all", "إحصائيات البوت (مشرف) / Global stats (admin)"),
    BotCommand("clean", "تنظيف قديم (مشرف) / Cleanup (admin)"),
]


async def sync_role_cache_task(app: Application) -> None:
    """Load roles from DB into the in-memory role cache."""
    from bot.services.security import sync_role_cache
    from database.models import Role

    repo = get_repository()
    for u in await repo.list_users(limit=2000):
        role_name = u.role.name if isinstance(u.role, Role) else str(u.role)
        sync_role_cache(u.telegram_id, role_name)


async def post_init(app: Application) -> None:
    repo = get_repository()
    await repo.init_models()
    await sync_role_cache_task(app)
    await app.bot.set_my_commands(COMMAND_DESCRIPTIONS)

    # in-process tracking job (works without Celery for single-instance setups)
    if app.job_queue:
        app.job_queue.run_repeating(tracking_job, interval=600, first=45)
        app.job_queue.run_repeating(snapshot_job, interval=3600, first=120)

    # Prometheus exporter (separate lightweight HTTP thread)
    if SETTINGS.metrics_enabled:
        try:
            from prometheus_client import start_http_server
            start_http_server(SETTINGS.metrics_port)
            log.info("metrics on :%s/metrics", SETTINGS.metrics_port)
        except Exception as exc:  # noqa: BLE001
            log.warning("metrics server failed: %s", exc)

    log.info("bot initialised — polling=%s", not SETTINGS.webhook_url)


async def post_shutdown(app: Application) -> None:
    await get_repository().dispose()
    log.info("bot shutdown complete")


async def tracking_job(context) -> None:  # ContextTypes.DEFAULT_TYPE
    """Notify tracked-account changes (username/bio/avatar/±10%/new video/verified)."""
    from bot.services.tracker import TrackingService

    try:
        notifications = await TrackingService(get_repository()).check_all()
        for note in notifications:
            await context.bot.send_message(note["telegram_id"], note["text"])
    except Exception as exc:  # noqa: BLE001
        log.warning("tracking job failed: %s", exc)


async def snapshot_job(context) -> None:
    """Hourly snapshots for tracked accounts to power 30-day growth charts."""
    from bot.services.tracker import TrackingService

    try:
        repo = get_repository()
        service = TrackingService(repo)
        usernames = {row.tiktok_username for row in await repo.list_tracked(only_active=True)}
        for username in usernames:
            result = await service.client.fetch_profile(username, want_videos=3)
            if result.ok:
                await service.take_snapshot(result.data)
    except Exception as exc:  # noqa: BLE001
        log.warning("snapshot job failed: %s", exc)


async def error_handler(update: object, context) -> None:
    log.error("unhandled error", exc_info=context.error)
    if getattr(update, "effective_message", None):
        try:
            await update.effective_message.reply_text(t("ar", "error_generic"))
        except Exception:  # noqa: BLE001
            pass


def create_app() -> Application:
    if not SETTINGS.bot_token:
        raise SystemExit("BOT_TOKEN is empty — copy docker/.env.example to docker/.env and fill it in.")
    setup_logging(SETTINGS.log_level)

    if SETTINGS.sentry_dsn:
        import sentry_sdk
        sentry_sdk.init(dsn=SETTINGS.sentry_dsn, traces_sample_rate=0.1)

    app = (ApplicationBuilder()
           .token(SETTINGS.bot_token)
           .post_init(post_init)
           .post_shutdown(post_shutdown)
           .concurrent_updates(True)
           .build())

    # commands
    for name, handler in commands.COMMANDS.items():
        app.add_handler(CommandHandler(name, handler), group=0)

    # inline buttons & free text
    app.add_handler(CallbackQueryHandler(callbacks.callback_router), group=1)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, messages.text_router), group=2)

    # global error handler
    app.add_error_handler(error_handler)
    return app


def main() -> None:
    app = create_app()
    if SETTINGS.webhook_url:
        secret = SETTINGS.webhook_secret or "tg-webhook"
        app.run_webhook(
            listen="0.0.0.0",
            port=SETTINGS.webhook_port,
            url_path=secret,
            webhook_url=f"{SETTINGS.webhook_url.rstrip('/')}/{secret}",
            allowed_updates=["message", "callback_query"],
        )
    else:
        app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
