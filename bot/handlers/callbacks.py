"""
Inline callback router — 3-level menus:

L1  main        (m:main)
L2  categories  (m:scan / m:analytics / m:track / m:reports / m:settings / m:help)
L3  actions     (sc:quick / an:content / lv:basic / rp:pdf:<u> / ...)
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.handlers.commands import main_menu_kb, perform_scan, run_compare, generate_and_send_report
from bot.utils.i18n import t
from bot.utils.logger import get_logger
from bot.utils.validators import clean_username
from database.repository import get_repository

log = get_logger(__name__)
REPO = get_repository()


def _back(lang: str, target: str = "m:main") -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(t(lang, "btn_back"), callback_data=target)]


def scan_menu(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(lang, "btn_quick_scan"), callback_data="sc:quick"),
         InlineKeyboardButton(t(lang, "btn_deep_scan"), callback_data="sc:deep")],
        [InlineKeyboardButton(t(lang, "btn_bulk"), callback_data="sc:bulk"),
         InlineKeyboardButton(t(lang, "btn_compare"), callback_data="sc:compare")],
        _back(lang),
    ])


def analytics_menu(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(lang, "btn_content"), callback_data="an:content")],
        [InlineKeyboardButton(t(lang, "btn_audience"), callback_data="an:audience")],
        [InlineKeyboardButton(t(lang, "btn_growth"), callback_data="an:growth")],
        _back(lang),
    ])


def reports_menu(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("PDF", callback_data="rp:pdf"),
         InlineKeyboardButton("HTML", callback_data="rp:html"),
         InlineKeyboardButton("Excel", callback_data="rp:xlsx"),
         InlineKeyboardButton("JSON", callback_data="rp:json")],
        _back(lang),
    ])


def settings_menu(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(lang, "btn_language"), callback_data="m:language")],
        [InlineKeyboardButton(t(lang, "btn_detail"), callback_data="m:detail")],
        _back(lang),
    ])


def language_menu(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🇸🇦 العربية", callback_data="lg:ar"),
         InlineKeyboardButton("🇬🇧 English", callback_data="lg:en")],
        _back(lang, "m:settings"),
    ])


def detail_menu(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 " + t(lang, "level_basic"), callback_data="lv:basic"),
         InlineKeyboardButton("🔵 " + t(lang, "level_advanced"), callback_data="lv:advanced"),
         InlineKeyboardButton("🔴 " + t(lang, "level_expert"), callback_data="lv:expert")],
        _back(lang, "m:settings"),
    ])


# ══════════════════════════════════════════════════════════════
async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    db_user = await REPO.get_user(update.effective_user.id)
    lang = db_user.language if db_user and db_user.language else "ar"
    data = query.data or ""

    # ── L1 / L2 navigation ───────────────────────────────────
    if data == "m:main":
        await query.edit_message_text(t(lang, "main_menu"), reply_markup=main_menu_kb(lang))
    elif data == "m:scan":
        await query.edit_message_text(t(lang, "main_menu"), reply_markup=scan_menu(lang))
    elif data == "m:analytics":
        await query.edit_message_text(t(lang, "main_menu"), reply_markup=analytics_menu(lang))
    elif data == "m:track":
        rows = await REPO.list_tracked(update.effective_user.id)
        text = (t(lang, "track_list", n=len(rows)) + "\n" +
                "\n".join(f"• @{r.tiktok_username}" for r in rows)) if rows else t(lang, "track_empty")
        kb = InlineKeyboardMarkup([_back(lang)])
        await query.edit_message_text(text, reply_markup=kb)
    elif data == "m:reports":
        await query.edit_message_text(t(lang, "main_menu"), reply_markup=reports_menu(lang))
    elif data == "m:settings":
        await query.edit_message_text(t(lang, "main_menu"), reply_markup=settings_menu(lang))
    elif data == "m:language":
        await query.edit_message_text(t(lang, "choose_lang"), reply_markup=language_menu(lang))
    elif data == "m:detail":
        await query.edit_message_text(t(lang, "choose_level"), reply_markup=detail_menu(lang))
    elif data == "m:help":
        kb = InlineKeyboardMarkup([_back(lang)])
        await query.edit_message_text(t(lang, "help_text"), reply_markup=kb)

    # ── L3 actions ───────────────────────────────────────────
    elif data == "sc:quick":
        context.user_data["await"] = "username_quick"
        await query.edit_message_text(t(lang, "send_username"))
    elif data == "sc:deep":
        context.user_data["await"] = "username_deep"
        await query.edit_message_text(t(lang, "send_username"))
    elif data == "sc:bulk":
        context.user_data["await"] = "bulk"
        await query.edit_message_text(t(lang, "send_bulk", limit=25))
    elif data == "sc:compare":
        context.user_data["await"] = "compare"
        await query.edit_message_text(t(lang, "send_two_usernames"))
    elif data == "lg:ar" or data == "lg:en":
        await REPO.set_language(update.effective_user.id, data.split(":")[1])
        lang = data.split(":")[1]
        await query.edit_message_text(t(lang, "lang_changed"), reply_markup=main_menu_kb(lang))
    elif data.startswith("lv:"):
        level = data.split(":")[1]
        await REPO.set_detail_level(update.effective_user.id, level)
        await query.edit_message_text(
            t(lang, "level_changed", level=t(lang, f"level_{level}")),
            reply_markup=settings_menu(lang))
    elif data.startswith("rp:"):
        fmt = data.split(":")[1]
        context.user_data["await"] = f"report_{fmt}"
        await query.edit_message_text(t(lang, "send_username"))
    elif data.startswith("hi:"):
        username = clean_username(data[3:])
        if username:
            await perform_scan(update, context, username, deep=False)
    elif data.startswith("ad:"):
        await _admin_actions(update, context, data.split(":")[1], lang)


async def _admin_actions(update: Update, context: ContextTypes.DEFAULT_TYPE,
                         action: str, lang: str) -> None:
    from telegram import InlineKeyboardButton as IB

    query = update.callback_query
    if action == "users":
        users = await REPO.list_users(limit=20)
        text = "👥 <b>Recent users</b>\n" + "\n".join(
            f"• {u.telegram_id} — @{u.username or '—'} ({u.role.name})" for u in users)
        await query.edit_message_text(text[:4000],
                                      reply_markup=InlineKeyboardMarkup([_back(lang)]))
    elif action == "stats":
        stats = await REPO.global_stats()
        await query.edit_message_text(
            t(lang, "stats_all", **stats),
            reply_markup=InlineKeyboardMarkup([_back(lang)]))
    elif action == "clean":
        from scripts.cleanup import run_cleanup
        scans_del, files_del = run_cleanup()
        await query.edit_message_text(
            t(lang, "clean_done", scans=scans_del, files=files_del),
            reply_markup=InlineKeyboardMarkup([_back(lang)]))
    elif action == "broadcast":
        context.user_data["await"] = "broadcast"
        await query.edit_message_text("📣 Send the broadcast text now:")
