"""
Free-text message router — drives the input flows started by menus/commands:
username input, bulk lists, compare pairs, report username, broadcast text.
Every payload passes the IDS (injection) filter before touching storage.
"""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from bot.handlers.commands import generate_and_send_report, perform_scan, run_bulk, run_compare
from bot.utils.decorators import get_lang
from bot.utils.i18n import t
from bot.utils.logger import get_logger
from bot.utils.validators import clean_username, detect_injection
from database.repository import get_repository

log = get_logger(__name__)
REPO = get_repository()


async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message or not update.effective_user:
        return
    lang = get_lang(update)
    raw = (update.effective_message.text or "").strip()
    state = context.user_data.get("await")

    # unsolicited text → gentle hint
    if not state:
        await update.effective_message.reply_text(t(lang, "main_menu"))
        return

    # security first: block injection-looking payloads early
    if detect_injection(raw):
        log.warning("injection blocked in message flow", extra={"user_id": update.effective_user.id})
        context.user_data["await"] = None
        await update.effective_message.reply_text(t(lang, "invalid_username"))
        return

    # ── single username flows ────────────────────────────────
    if state in {"username_quick", "username_deep"}:
        username = clean_username(raw)
        context.user_data["await"] = None
        if not username:
            await update.effective_message.reply_text(t(lang, "invalid_username"))
            return
        await perform_scan(update, context, username, deep=(state == "username_deep"))

    # ── bulk ─────────────────────────────────────────────────
    elif state == "bulk":
        names = [u for u in (clean_username(x) or "" for x in
                             raw.replace("\n", " ").replace(",", " ").split()) if u]
        context.user_data["await"] = None
        if not names:
            await update.effective_message.reply_text(t(lang, "invalid_username"))
            return
        await run_bulk(update, names)

    # ── compare pair ─────────────────────────────────────────
    elif state == "compare":
        names = [u for u in (clean_username(x) or "" for x in raw.split()) if u]
        context.user_data["await"] = None
        if len(names) != 2:
            await update.effective_message.reply_text(t(lang, "send_two_usernames"))
            return
        await run_compare(update, names[0], names[1])

    # ── report flows ─────────────────────────────────────────
    elif state.startswith("report_"):
        fmt = state.split("_", 1)[1]
        username = clean_username(raw)
        context.user_data["await"] = None
        if not username:
            await update.effective_message.reply_text(t(lang, "invalid_username"))
            return
        await generate_and_send_report(update, context, username, fmt)

    # ── broadcast (admins only reach this state) ─────────────
    elif state == "broadcast":
        context.user_data["await"] = None
        from bot.handlers.commands import run_broadcast
        await run_broadcast(update, context, raw)
