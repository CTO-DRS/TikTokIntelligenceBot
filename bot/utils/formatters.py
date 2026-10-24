"""Telegram message formatters — bilingual, HTML parse-mode, 3 detail levels."""
from __future__ import annotations

import html
from datetime import datetime, timezone

from bot.services.analytics import DOW_AR, DOW_EN
from bot.utils.i18n import t
from bot.utils.validators import sanitize_text

LEVELS = {"basic": 1, "advanced": 2, "expert": 3}


def fmt_escape(text: str | None) -> str:
    """HTML-escape short dynamic labels (usernames etc.) for Telegram HTML."""
    return html.escape(str(text or ""), quote=False)


def fmt_num(n: int | float | None) -> str:
    """1_234_567 → '1.23M' style compact formatting."""
    if n is None:
        return "—"
    n = float(n)
    for div, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if abs(n) >= div:
            return f"{n / div:.2f}{suffix}"
    return f"{int(n)}" if float(n).is_integer() else f"{n:.1f}"


def fmt_bool(v: bool | None, lang: str) -> str:
    if v is None:
        return t(lang, "na")
    return "✅" if v else "❌"


def _na(lang: str) -> str:
    return f"❌ {t(lang, 'na')}"


def _row(lang: str, key: str, value: object) -> str:
    return f"• {t(lang, key)}: <b>{value}</b>"


def _section(lang: str, key: str) -> str:
    return f"\n{t(lang, key)}\n"


def _fmt_ts(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(str(iso))
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except (TypeError, ValueError):
        return str(iso)[:19]


def build_profile_message(profile: dict, lang: str, level: str = "advanced") -> str:
    """Compose the main scan result message at the requested detail level."""
    lvl = LEVELS.get(level, 2)
    lines: list[str] = []
    demo = profile.get("demo")

    if demo:
        lines.append(t(lang, "demo_warning"))

    # ── identity ─────────────────────────────────────────────
    lines.append(_section(lang, "sec_identity"))
    lines.append(_row(lang, "f_username", "@" + str(profile.get("username", "?"))))
    uid = profile.get("id")
    lines.append(_row(lang, "f_user_id", uid or _na(lang)))
    lines.append(_row(lang, "f_name", sanitize_text(profile.get("nickname"), 100)))
    bio = sanitize_text(profile.get("bio"), 300) or "—"
    lines.append(_row(lang, "f_bio", bio))
    lines.append(_row(lang, "f_private", fmt_bool(profile.get("private"), lang)))
    lines.append(_row(lang, "f_verified", fmt_bool(profile.get("verified"), lang)))
    region = profile.get("region")
    lines.append(_row(lang, "f_region", region if region else _na(lang)))
    language = profile.get("language")
    lines.append(_row(lang, "f_language", language if language else _na(lang)))
    # creation time is not public — honest marker
    lines.append(_row(lang, "f_created", _na(lang)))

    if profile.get("avatar"):
        lines.append(_row(lang, "f_avatar", "🖼 " + str(profile["avatar"])[:120]))

    # ── stats ────────────────────────────────────────────────
    lines.append(_section(lang, "sec_stats"))
    lines.append(_row(lang, "f_followers", fmt_num(profile.get("followers"))))
    lines.append(_row(lang, "f_following", fmt_num(profile.get("following"))))
    lines.append(_row(lang, "f_likes", fmt_num(profile.get("likes"))))
    lines.append(_row(lang, "f_videos", fmt_num(profile.get("videos_count"))))
    lines.append(_row(lang, "f_views", fmt_num(profile.get("total_views"))))
    lines.append(_row(lang, "f_avg_views", fmt_num(profile.get("avg_views"))))

    if lvl >= 2:
        er = profile.get("engagement_rate")
        er_txt = f"{er:.2f}%" if isinstance(er, (int, float)) else _na(lang)
        lines.append(_row(lang, "f_engagement", er_txt))

        # ── advanced / geo / device (honest) ─────────────────
        lines.append(_section(lang, "sec_advanced"))
        emails = profile.get("emails") or []
        phones = profile.get("phones") or []
        lines.append(_row(lang, "f_email",
                          ", ".join(html.escape(e) for e in emails) if emails else _na(lang) + " ℹ️"))
        lines.append(_row(lang, "f_phone",
                          ", ".join(html.escape(p) for p in phones) if phones else _na(lang) + " ℹ️"))

        lines.append(_section(lang, "sec_geo"))
        geo = profile.get("geo") or {}
        if geo.get("country") or geo.get("city"):
            lines.append(_row(lang, "f_city", f"{geo.get('city', '—')} / {geo.get('country', '—')}"))
            lines.append(_row(lang, "f_timezone", geo.get("timezone", "—")))
            if geo.get("isp"):
                lines.append(_row(lang, "f_isp", html.escape(str(geo["isp"]))))
        else:
            lines.append(_row(lang, "f_gps", _na(lang)))
            lines.append(_row(lang, "f_city", _na(lang)))
        lines.append(_row(lang, "f_creation_ip", _na(lang)))
        lines.append(_row(lang, "f_timezone", (geo or {}).get("timezone") or _na(lang)))

        lines.append(_section(lang, "sec_device"))
        dev = profile.get("device") or {}
        lines.append(_row(lang, "f_device_model", dev.get("model") or _na(lang)))
        lines.append(_row(lang, "f_os", dev.get("os") or _na(lang)))
        lines.append(_row(lang, "f_app_version", dev.get("app_version") or _na(lang)))
        lines.append(_row(lang, "f_device_id", _na(lang)))
        lines.append(_row(lang, "f_network", _na(lang)))

        # ── socials ──────────────────────────────────────────
        socials = profile.get("socials") or {}
        bio_link = profile.get("bio_link")
        if socials or bio_link:
            lines.append(_section(lang, "sec_social"))
            for net, handle in socials.items():
                lines.append(f"• {html.escape(net)}: {html.escape(str(handle))}")
            if bio_link:
                lines.append(f"• 🔗 {html.escape(str(bio_link))[:120]}")

    if lvl >= 2 and profile.get("videos"):
        lines.append(_section(lang, "sec_content"))
        vids = profile["videos"][:5]
        views_key = t(lang, "view_video")
        for i, v in enumerate(vids, 1):
            lines.append(
                f"{i}. 🕒 {_fmt_ts(v.get('create_time'))} | {views_key}: "
                f"<b>{fmt_num(v.get('views'))}</b> ❤️ {fmt_num(v.get('likes'))} "
                f"💬 {fmt_num(v.get('comments'))} 🔁 {fmt_num(v.get('shares'))}"
            )
        if profile.get("top_hashtags"):
            tags = " ".join("#" + html.escape(tag) for tag, _ in profile["top_hashtags"][:8])
            lines.append(f"\n{t(lang, 'f_top_hashtags')}: {tags}")

    if lvl >= 3:
        lines.append(_section(lang, "sec_security"))
        sec = profile.get("security") or {}
        score = sec.get("score")
        lines.append(_row(lang, "security_score", f"{'🟢' if (score or 0) >= 70 else '🟡' if (score or 0) >= 40 else '🔴'} {score if score is not None else _na(lang)}/100"))
        lines.append("\n" + t(lang, "privacy_note"))
        src = profile.get("source")
        lines.append(f"\n🔎 <i>source: {html.escape(str(src))} | fetched: {_fmt_ts(profile.get('fetched_at'))}</i>")

    return "\n".join(lines)


def build_compare_message(rows: list[tuple[str, object, object]], lang: str, header: str) -> str:
    """rows: list of (label, value_a, value_b)."""
    lines = [header, ""]
    width = max((len(r[0]) for r in rows), default=10)
    lines.append(f"<code>{'المقياس' if lang == 'ar' else 'Metric':<{width}} | A | B</code>")
    for label, a, b in rows:
        lines.append(f"<code>{html.escape(str(label)):<{width}} | {html.escape(str(a))} | {html.escape(str(b))}</code>")
    return "\n".join(lines)


def build_history_message(items: list[dict], lang: str) -> str:
    if not items:
        return t(lang, "no_history")
    lines = [t(lang, "history_title"), ""]
    for i, item in enumerate(items, 1):
        lines.append(
            f"{i}. @{html.escape(str(item.get('target_username')))} — "
            f"{html.escape(str(item.get('scan_type')))} — {_fmt_ts(item.get('created_at'))}"
        )
    return "\n".join(lines)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "LEVELS", "fmt_num", "fmt_bool", "fmt_escape", "build_profile_message",
    "build_compare_message", "build_history_message", "now_iso",
    "DOW_AR", "DOW_EN",
]
