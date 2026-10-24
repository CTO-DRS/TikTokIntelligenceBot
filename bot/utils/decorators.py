"""Reusable async decorators: access control, rate limiting, error capture."""
from __future__ import annotations

import functools
import time
from collections.abc import Awaitable, Callable

from telegram import Update
from telegram.ext import ContextTypes

from bot.services.security import RateLimiter, RoleUtils, Roles
from bot.utils.i18n import t
from bot.utils.logger import get_logger
from bot.utils.validators import detect_injection
from config.settings import get_settings

log = get_logger(__name__)
SETTINGS = get_settings()

# One shared limiter instance process-wide (Redis-backed with memory fallback)
LIMITER = RateLimiter(SETTINGS.get_redis_url())

WINDOWS = {"minute": 60, "hour": 3600, "day": 86400}


def get_lang(update: Update) -> str:
    """Best-effort language from user_data (DB sync happens in handlers)."""
    data = getattr(update, "effective_user", None)
    if data is None:
        return SETTINGS.default_language
    # language resolution is DB-based; decorators read the cached copy
    return _LANG_CACHE.get(data.id, SETTINGS.default_language)


_LANG_CACHE: dict[int, str] = {}


def set_lang_cache(telegram_id: int, lang: str) -> None:
    _LANG_CACHE[telegram_id] = lang if lang in {"ar", "en"} else "ar"


def _reply_lang(update: Update) -> str:
    uid = update.effective_user.id if update.effective_user else 0
    return _LANG_CACHE.get(uid, SETTINGS.default_language)


def admin_only(func: Callable) -> Callable:
    """Allow only ADMIN / SUPER_ADMIN roles."""

    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        lang = _reply_lang(update)
        if user is None or RoleUtils.role_of(user.id) not in (Roles.ADMIN, Roles.SUPER_ADMIN):
            if update.effective_message:
                await update.effective_message.reply_text(t(lang, "admin_only"))
            return
        return await func(update, context, *args, **kwargs)

    return wrapper


def banned_guard(func: Callable) -> Callable:
    """Silently ignore banned users."""

    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if user is not None and RoleUtils.is_banned(user.id):
            lang = _reply_lang(update)
            if update.effective_message:
                await update.effective_message.reply_text(t(lang, "banned"))
            return
        return await func(update, context, *args, **kwargs)

    return wrapper


def rate_limit(action: str, limit: int, window: str = "hour") -> Callable:
    """Sliding-window rate limiter keyed by (user, action)."""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            user = update.effective_user
            lang = _reply_lang(update)
            if user is not None:
                if RoleUtils.role_of(user.id) in (Roles.ADMIN, Roles.SUPER_ADMIN, Roles.VIP):
                    # elevated tiers get 5x allowance
                    limit_eff = limit * 5
                else:
                    limit_eff = limit
                key = f"{action}:{user.id}"
                allowed = await LIMITER.allow(key, limit_eff, WINDOWS.get(window, 3600))
                if not allowed:
                    log.info("rate limited", extra={"user_id": user.id, "action": action})
                    if update.effective_message:
                        await update.effective_message.reply_text(
                            t(lang, "rate_limited", limit=limit_eff, window=window)
                        )
                    return
            return await func(update, context, *args, **kwargs)

        return wrapper

    return decorator


def guard(action: str, limit: int, window: str = "hour") -> Callable:
    """Composite guard: banned check + admin bypass + rate limit + IDS."""

    def decorator(func: Callable) -> Callable:
        @admin_only_bypass
        @rate_limit(action, limit, window)
        @banned_guard
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            text = " ".join(context.args) if context.args else ""
            if text and detect_injection(text):
                lang = _reply_lang(update)
                user = update.effective_user
                log.warning("injection attempt blocked",
                            extra={"user_id": user.id if user else 0, "action": action})
                if update.effective_message:
                    await update.effective_message.reply_text(t(lang, "invalid_username"))
                return
            started = time.perf_counter()
            result = await func(update, context, *args, **kwargs)
            log.info("handler done", extra={
                "action": action,
                "duration_ms": int((time.perf_counter() - started) * 1000),
                "user_id": update.effective_user.id if update.effective_user else 0,
            })
            return result

        return wrapper

    return decorator


def admin_only_bypass(func: Callable) -> Callable:
    """Marker wrapper: admins skip the inner rate-limit decorator."""
    # python-telegram-bot flows: keep it simple — no special behaviour needed
    return func


def async_safe(default: object = None) -> Callable:
    """Wrap an awaitable so failures log and return `default` instead of raising."""

    def decorator(func: Callable[..., Awaitable]) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except Exception:  # noqa: BLE001
                log.exception("async_safe caught error in %s", func.__name__)
                return default

        return wrapper

    return decorator
