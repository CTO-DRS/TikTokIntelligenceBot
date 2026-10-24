"""
The 17 commands.

/start /scan /deepscan /bulk /compare /track /stats /report /history
/settings /export /admin /broadcast /block /unblock /stats_all /clean
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.services.analytics import AnalyticsEngine, CompareService
from bot.services.security import ProfileSecurityScorer, RoleUtils, Roles, sync_role_cache
from bot.services.tiktok_api import bulk_fetch
from bot.utils import formatters
from bot.utils.decorators import admin_only, guard, get_lang, rate_limit, set_lang_cache, LIMITER
from bot.utils.i18n import t
from bot.utils.logger import get_logger
from bot.utils.validators import clean_username, safe_filename
from config.settings import get_settings
from database.models import ReportKind, Role, ScanType
from database.repository import get_repository

log = get_logger(__name__)
SETTINGS = get_settings()
REPO = get_repository()
MAX_BULK_USER = 5
MAX_BULK_VIP = 25


# ══════════════════════════════════════════════════════════════
# helpers shared with callbacks.py / messages.py
# ══════════════════════════════════════════════════════════════
async def _user_lang(update: Update) -> str:
    user = update.effective_user
    db_user = await REPO.ensure_user(user.id, user.username, user.first_name)
    set_lang_cache(user.id, db_user.language)
    sync_role_cache(user.id, db_user.role.name if isinstance(db_user.role, Role) else str(db_user.role))
    return db_user.language


async def _user_level(update: Update) -> str:
    user = update.effective_user
    db_user = await REPO.get_user(user.id)
    return (db_user.detail_level if db_user else "advanced")


def main_menu_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(lang, "btn_scan"), callback_data="m:scan"),
         InlineKeyboardButton(t(lang, "btn_analytics"), callback_data="m:analytics")],
        [InlineKeyboardButton(t(lang, "btn_tracking"), callback_data="m:track"),
         InlineKeyboardButton(t(lang, "btn_reports"), callback_data="m:reports")],
        [InlineKeyboardButton(t(lang, "btn_settings"), callback_data="m:settings"),
         InlineKeyboardButton(t(lang, "btn_help"), callback_data="m:help")],
    ])


async def perform_scan(update: Update, context: ContextTypes.DEFAULT_TYPE,
                       username: str, deep: bool) -> None:
    """Core scan flow shared by /scan, /deepscan and the inline menus."""
    lang = await _user_lang(update)
    msg = await update.effective_message.reply_text(t(lang, "scanning", username=username))
    import time as _time
    started = _time.perf_counter()

    client_kwargs = {"want_videos": SETTINGS.videos_deep_count} if deep else {"want_videos": 5}
    from bot.services.tiktok_api import TikTokClient
    client = TikTokClient()
    try:
        result = await client.fetch_profile(username, **client_kwargs)
    finally:
        await client.close()

    duration_ms = int((_time.perf_counter() - started) * 1000)
    if not result.ok:
        await msg.edit_text(t(lang, "user_not_found"))
        await REPO.add_scan(update.effective_user.id, username,
                            ScanType.DEEP if deep else ScanType.BASIC,
                            status="FAIL", duration_ms=duration_ms)
        return

    profile = result.data
    snapshots = await REPO.snapshots(username, days=30)
    engine = AnalyticsEngine(snapshots=snapshots)
    engine.analyze(profile)
    profile["security"] = ProfileSecurityScorer.score(profile)
    if not deep:
        profile["videos"] = (profile.get("videos") or [])[:5]

    level = await _user_level(update)
    text = formatters.build_profile_message(profile, lang, level)
    context.user_data[f"scan:{username.lower()}"] = profile

    await REPO.add_scan(update.effective_user.id, username,
                        ScanType.DEEP if deep else ScanType.BASIC,
                        status="DEMO" if profile.get("demo") else "OK",
                        duration_ms=duration_ms)
    # keep snapshot history for tracked accounts (growth charts)
    for tracked in await REPO.list_tracked(update.effective_user.id):
        if tracked.tiktok_username.lower() == username.lower():
            from bot.services.tracker import TrackingService
            await TrackingService(REPO).take_snapshot(profile)
            break

    chunk = text[:4000]
    await msg.edit_text(chunk, disable_web_page_preview=True)
    if len(text) > 4000:
        await update.effective_message.reply_text(text[4000:8000], disable_web_page_preview=True)


# ══════════════════════════════════════════════════════════════
# /start
# ══════════════════════════════════════════════════════════════
@guard("start", limit=30, window="minute")
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await _user_lang(update)
    name = update.effective_user.first_name or update.effective_user.username or "friend"
    await update.effective_message.reply_text(
        t(lang, "welcome", name=formatters.fmt_escape(name)),
        reply_markup=main_menu_kb(lang), disable_web_page_preview=True,
    )


# ══════════════════════════════════════════════════════════════
# /scan  /deepscan
# ══════════════════════════════════════════════════════════════
@guard("scan", limit=SETTINGS.rate_limit_scan_hour)
async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await _user_lang(update)
    username = clean_username(" ".join(context.args)) if context.args else None
    if not username:
        context.user_data["await"] = "username_quick"
        await update.effective_message.reply_text(t(lang, "send_username"))
        return
    await perform_scan(update, context, username, deep=False)


@guard("deepscan", limit=SETTINGS.rate_limit_deep_hour)
async def cmd_deepscan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await _user_lang(update)
    username = clean_username(" ".join(context.args)) if context.args else None
    if not username:
        context.user_data["await"] = "username_deep"
        await update.effective_message.reply_text(t(lang, "send_username"))
        return
    await perform_scan(update, context, username, deep=True)


# ══════════════════════════════════════════════════════════════
# /bulk
# ══════════════════════════════════════════════════════════════
@guard("bulk", limit=SETTINGS.rate_limit_bulk_hour)
async def cmd_bulk(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await _user_lang(update)
    raw = " ".join(context.args) if context.args else ""
    names = [u for u in (clean_username(x) or "" for x in raw.replace("\n", " ").replace(",", " ").split()) if u]
    if not names:
        context.user_data["await"] = "bulk"
        await update.effective_message.reply_text(t(lang, "send_bulk", limit=MAX_BULK_VIP))
        return
    await run_bulk(update, names)


async def run_bulk(update: Update, names: list[str]) -> None:
    lang = await _user_lang(update)
    role = RoleUtils.role_of(update.effective_user.id)
    cap = MAX_BULK_VIP if role >= Roles.VIP else MAX_BULK_USER
    names = names[:cap]
    await update.effective_message.reply_text(
        t(lang, "scanning", username=f"{len(names)} accounts"))
    results = await bulk_fetch(names, concurrency=3, want_videos=5)
    lines = ["📦 <b>Bulk results</b>", ""]
    for name in names:
        res = results.get(name)
        if res and res.ok:
            p = res.data
            er = p.get("engagement_rate")
            lines.append(
                f"• @{name}: 👥 {formatters.fmt_num(p.get('followers'))} "
                f"❤️ {formatters.fmt_num(p.get('likes'))} 🎬 {formatters.fmt_num(p.get('videos_count'))} "
                f"ER: {f'{er:.2f}%' if er else '—'}{' 🧪' if p.get('demo') else ''}")
        else:
            lines.append(f"• @{name}: ❌ not found")
    await update.effective_message.reply_text("\n".join(lines)[:4000], disable_web_page_preview=True)
    for name in names:
        res = results.get(name)
        if res and res.ok:
            await REPO.add_scan(update.effective_user.id, name, ScanType.BULK,
                                status="DEMO" if res.data.get("demo") else "OK")


# ══════════════════════════════════════════════════════════════
# /compare
# ══════════════════════════════════════════════════════════════
@guard("compare", limit=10)
async def cmd_compare(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await _user_lang(update)
    names = [u for u in (clean_username(x) or "" for x in context.args or []) if u]
    if len(names) != 2:
        context.user_data["await"] = "compare"
        await update.effective_message.reply_text(t(lang, "send_two_usernames"))
        return
    await run_compare(update, names[0], names[1])


async def run_compare(update: Update, a: str, b: str) -> None:
    lang = await _user_lang(update)
    results = await bulk_fetch([a, b], concurrency=2, want_videos=10)
    res_a, res_b = results.get(a), results.get(b)
    if not (res_a and res_a.ok and res_b and res_b.ok):
        await update.effective_message.reply_text(t(lang, "user_not_found"))
        return
    rows = CompareService.diff(res_a.data, res_b.data)
    text = formatters.build_compare_message(rows, lang, t(lang, "compare_done"))
    await update.effective_message.reply_text(text[:4000], disable_web_page_preview=True)
    for name, res in ((a, res_a), (b, res_b)):
        await REPO.add_scan(update.effective_user.id, name, ScanType.COMPARE,
                            status="DEMO" if res.data.get("demo") else "OK")


# ══════════════════════════════════════════════════════════════
# /track
# ══════════════════════════════════════════════════════════════
@guard("track", limit=30)
async def cmd_track(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await _user_lang(update)
    args = context.args or []
    if not args:
        rows = await REPO.list_tracked(update.effective_user.id)
        if not rows:
            await update.effective_message.reply_text(t(lang, "track_empty"))
        else:
            lines = [t(lang, "track_list", n=len(rows))]
            lines += [f"• @{r.tiktok_username}" for r in rows]
            await update.effective_message.reply_text("\n".join(lines))
        return
    action = args[0].lower()
    if action == "off" and len(args) >= 2:
        username = clean_username(" ".join(args[1:]))
        if username and await REPO.untrack_account(update.effective_user.id, username):
            await update.effective_message.reply_text(t(lang, "track_removed", username=username))
        else:
            await update.effective_message.reply_text(t(lang, "track_empty"))
        return
    username = clean_username(" ".join(args))
    if not username:
        await update.effective_message.reply_text(t(lang, "invalid_username"))
        return
    await REPO.track_account(update.effective_user.id, username)
    await REPO.audit(update.effective_user.id, "track", username)
    await update.effective_message.reply_text(t(lang, "track_added", username=username))


# ══════════════════════════════════════════════════════════════
# /stats  /history
# ══════════════════════════════════════════════════════════════
@guard("stats", limit=30, window="minute")
async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await _user_lang(update)
    scans = await REPO.user_scan_count(update.effective_user.id)
    tracked = len(await REPO.list_tracked(update.effective_user.id))
    db_user = await REPO.get_user(update.effective_user.id)
    since = db_user.created_at.strftime("%Y-%m-%d") if db_user and db_user.created_at else "—"
    await update.effective_message.reply_text(
        t(lang, "my_stats", scans=scans, tracked=tracked, since=since))


@guard("history", limit=30, window="minute")
async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await _user_lang(update)
    rows = await REPO.recent_scans(update.effective_user.id, limit=10)
    text = formatters.build_history_message(
        [{"target_username": r.target_username, "scan_type": r.scan_type.value,
          "created_at": r.created_at.isoformat() if r.created_at else ""} for r in rows], lang)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(
        f"🔄 @{r.target_username}", callback_data=f"hi:{r.target_username}")]
        for r in rows[:8]] or [[InlineKeyboardButton(t(lang, "btn_back"), callback_data="m:main")]])
    await update.effective_message.reply_text(text, reply_markup=kb)


# ══════════════════════════════════════════════════════════════
# /report  /export
# ══════════════════════════════════════════════════════════════
@guard("report", limit=SETTINGS.rate_limit_report_hour)
async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await _user_lang(update)
    args = context.args or []
    if not args:
        await update.effective_message.reply_text("Usage: /report @username [pdf|html|xlsx|json]")
        return
    username = clean_username(args[0])
    fmt = (args[1].lower() if len(args) > 1 else "pdf")
    if fmt not in {"pdf", "html", "xlsx", "json"}:
        await update.effective_message.reply_text(t(lang, "report_bad_type"))
        return
    if not username:
        await update.effective_message.reply_text(t(lang, "invalid_username"))
        return
    await generate_and_send_report(update, context, username, fmt)


async def generate_and_send_report(update: Update, context: ContextTypes.DEFAULT_TYPE,
                                   username: str, fmt: str) -> None:
    lang = await _user_lang(update)
    status = await update.effective_message.reply_text(
        t(lang, "report_generating", fmt=fmt.upper(), username=username))
    profile = context.user_data.get(f"scan:{username.lower()}")
    if profile is None:
        from bot.services.tiktok_api import TikTokClient
        client = TikTokClient()
        try:
            result = await client.fetch_profile(username, want_videos=SETTINGS.videos_deep_count)
        finally:
            await client.close()
        if not result.ok:
            await status.edit_text(t(lang, "user_not_found"))
            return
        profile = result.data

    snapshots = await REPO.snapshots(username, days=30)
    analytics = AnalyticsEngine(snapshots=snapshots).analyze(profile)
    profile["security"] = ProfileSecurityScorer.score(profile)

    out_dir = Path(SETTINGS.report_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = safe_filename(username)
    if fmt == "pdf":
        from reports.generators.pdf_generator import PDFReport
        path = out_dir / f"report_{safe}.pdf"
        PDFReport(lang=lang).build(profile, analytics, path)
        kind = ReportKind.PDF
    elif fmt == "html":
        from reports.generators.html_generator import HTMLReport
        path = out_dir / f"report_{safe}.html"
        HTMLReport(lang=lang).build(profile, analytics, path)
        kind = ReportKind.HTML
    elif fmt == "xlsx":
        from reports.generators.excel_generator import ExcelReport
        path = out_dir / f"report_{safe}.xlsx"
        ExcelReport(lang=lang).build(profile, analytics, snapshots, path)
        kind = ReportKind.EXCEL
    else:
        path = out_dir / f"report_{safe}.json"
        payload = {"profile": {k: v for k, v in profile.items() if k != "videos"},
                   "videos": profile.get("videos")[:30], "analytics": _jsonable(analytics)}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                        encoding="utf-8")
        kind = ReportKind.JSON

    await REPO.add_report(kind=kind, path=str(path), size_bytes=path.stat().st_size,
                          telegram_user_id=update.effective_user.id)
    with path.open("rb") as fh:
        await update.effective_message.reply_document(fh, filename=path.name)
    await status.edit_text(t(lang, "report_done"))


def _jsonable(obj: object) -> object:
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (int, float, str, bool)) or obj is None:
        return obj
    return str(obj)


@guard("export", limit=3)
async def cmd_export(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await _user_lang(update)
    rows = await REPO.recent_scans(update.effective_user.id, limit=100)
    tracked = await REPO.list_tracked(update.effective_user.id)
    payload = {
        "telegram_id": update.effective_user.id,
        "scans": [{"target": r.target_username, "type": r.scan_type.value,
                   "at": r.created_at.isoformat() if r.created_at else None} for r in rows],
        "tracked": [r.tiktok_username for r in tracked],
    }
    path = Path(SETTINGS.report_dir) / f"export_{update.effective_user.id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with path.open("rb") as fh:
        await update.effective_message.reply_document(fh, filename=path.name)
    await update.effective_message.reply_text(t(lang, "export_done"))


# ══════════════════════════════════════════════════════════════
# /settings
# ══════════════════════════════════════════════════════════════
@guard("settings", limit=30, window="minute")
async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await _user_lang(update)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(t(lang, "btn_language"), callback_data="m:language")],
        [InlineKeyboardButton(t(lang, "btn_detail"), callback_data="m:detail")],
        [InlineKeyboardButton(t(lang, "btn_back"), callback_data="m:main")],
    ])
    await update.effective_message.reply_text(t(lang, "main_menu"), reply_markup=kb)


# ══════════════════════════════════════════════════════════════
# admin: /admin /broadcast /block /unblock /stats_all /clean
# ══════════════════════════════════════════════════════════════
@admin_only
async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await _user_lang(update)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Users", callback_data="ad:users"),
         InlineKeyboardButton("🌐 Stats", callback_data="ad:stats")],
        [InlineKeyboardButton("🧹 Clean", callback_data="ad:clean"),
         InlineKeyboardButton("📣 Broadcast", callback_data="ad:broadcast")],
    ])
    await update.effective_message.reply_text(t(lang, "admin_panel"), reply_markup=kb)


@admin_only
@rate_limit("broadcast", 3, "day")
async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await _user_lang(update)
    text = " ".join(context.args) if context.args else ""
    if not text:
        context.user_data["await"] = "broadcast"
        await update.effective_message.reply_text("📣 Send the broadcast text now:")
        return
    await run_broadcast(update, context, text)


async def run_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    users = await REPO.list_users(limit=2000)
    ok = fail = 0
    for u in users:
        if u.is_blocked or u.role == Role.BANNED:
            continue
        try:
            await context.bot.send_message(u.telegram_id, f"📣 {text}")
            ok += 1
        except Exception:  # noqa: BLE001
            fail += 1
        await asyncio.sleep(0.05)  # ~20 msg/s, under Telegram limits
    lang = get_lang(update)
    await update.effective_message.reply_text(t(lang, "broadcast_done", ok=ok, fail=fail))
    await REPO.audit(update.effective_user.id, "broadcast", f"ok={ok},fail={fail}")


@admin_only
async def cmd_block(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = get_lang(update)
    if not context.args or not context.args[0].lstrip("-").isdigit():
        await update.effective_message.reply_text("Usage: /block <telegram_id>")
        return
    target = int(context.args[0])
    await REPO.set_role(target, Role.BANNED)
    await REPO.audit(update.effective_user.id, "block", str(target))
    await update.effective_message.reply_text(t(lang, "blocked", target=target))


@admin_only
async def cmd_unblock(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = get_lang(update)
    if not context.args or not context.args[0].lstrip("-").isdigit():
        await update.effective_message.reply_text("Usage: /unblock <telegram_id>")
        return
    target = int(context.args[0])
    await REPO.set_role(target, Role.USER)
    await REPO.audit(update.effective_user.id, "unblock", str(target))
    await update.effective_message.reply_text(t(lang, "unblocked", target=target))


@admin_only
async def cmd_stats_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = get_lang(update)
    stats = await REPO.global_stats()
    await update.effective_message.reply_text(
        t(lang, "stats_all", users=stats["users"], scans=stats["scans"],
          today=stats["today"], tracked=stats["tracked"],
          reports=stats["reports"], top=formatters.fmt_escape(stats["top"])))


@admin_only
async def cmd_clean(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from scripts.cleanup import run_cleanup
    lang = get_lang(update)
    scans_deleted, files_deleted = run_cleanup()
    await REPO.audit(update.effective_user.id, "clean")
    await update.effective_message.reply_text(
        t(lang, "clean_done", scans=scans_deleted, files=files_deleted))


# ══════════════════════════════════════════════════════════════
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    lang = await _user_lang(update)
    await update.effective_message.reply_text(t(lang, "help_text"))


COMMANDS = {
    "start": cmd_start, "scan": cmd_scan, "deepscan": cmd_deepscan,
    "bulk": cmd_bulk, "compare": cmd_compare, "track": cmd_track,
    "stats": cmd_stats, "report": cmd_report, "history": cmd_history,
    "settings": cmd_settings, "export": cmd_export, "admin": cmd_admin,
    "broadcast": cmd_broadcast, "block": cmd_block, "unblock": cmd_unblock,
    "stats_all": cmd_stats_all, "clean": cmd_clean, "help": cmd_help,
}
