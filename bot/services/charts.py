"""
Chart service — publication-quality PNG charts from PUBLIC data only.

Design rules (honoured by every function):
* ``constrained_layout=True`` — the ONLY layout engine used (no tight_layout /
  subplots_adjust / bbox_inches='tight', which conflict with it).
* Arabic labels: reshaped (arabic-reshaper) + bidi-reordered, rendered with an
  Arabic-capable font if one exists on the system; otherwise labels gracefully
  fall back to English so charts are never broken.
* Every function returns PNG bytes (``io.BytesIO``) so handlers can send them
  directly and generators can embed them.

Charts:
* growth_chart      — follower time-series (from AccountSnapshot points)
* posting_heatmap   — day-of-week × hour average views (from last videos)
* hashtags_bar      — top hashtags frequency
* engagement_mix    — donut of avg likes/comments/shares/saves per video
* save_charts       — convenience: renders the applicable set into files
"""
from __future__ import annotations

import io
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless servers

import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import numpy as np

from bot.services.analytics import DOW_AR, DOW_EN
from bot.utils.logger import get_logger

log = get_logger(__name__)

# ── Arabic-capable font discovery ────────────────────────────────────────────
_AR_FONT_NAME_HINTS = ("Naskh", "Arabic", "Amiri", "Kufi", "Noto Sans Arabic")
_AR_FONT_PATHS = (
    "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Bold.ttf",
    "/usr/share/fonts/truetype/kacst/KacstOne.ttf",
    "/usr/share/fonts/truetype/arabic/Amiri-Regular.ttf",
)


def _register_arabic_font() -> str | None:
    """Register an Arabic font with matplotlib; return its family or None."""
    candidates = list(_AR_FONT_PATHS)
    try:  # also scan installed fonts by name hint
        for f in fm.fontManager.ttflist:
            if any(h.lower() in f.name.lower() for h in _AR_FONT_NAME_HINTS):
                candidates.append(f.fname)
                break
    except Exception:  # noqa: BLE001 — font scan must never break charts
        pass
    for path in candidates:
        try:
            if Path(path).exists():
                fm.fontManager.addfont(path)
                return fm.FontProperties(fname=path).get_name()
        except Exception:  # noqa: BLE001
            continue
    return None


_AR_FAMILY: str | None = _register_arabic_font()

_BRAND = "#fe2c55"      # TikTok red
_BRAND2 = "#25f4ee"     # TikTok cyan
_INK = "#111111"
_MUTE = "#666666"
_GRID = "#e6e6e6"

try:  # arabic_reshaper + python-bidi are optional at chart level
    import arabic_reshaper
    from bidi.algorithm import get_display

    def _ar(text: str) -> str:
        return get_display(arabic_reshaper.reshape(str(text)))
except Exception:  # noqa: BLE001 — degrade to plain text
    def _ar(text: str) -> str:  # type: ignore[misc]
        return str(text)


def _L(lang: str, arabic: str, english: str) -> str:
    """Pick + shape a label. If Arabic requested but no Arabic font, use EN."""
    if (lang or "ar").lower() == "ar" and _AR_FAMILY:
        return _ar(arabic)
    return english


def _apply_style(fig: plt.Figure, axes, lang: str) -> None:
    if _AR_FAMILY and lang == "ar":
        for ax in np.atleast_1d(axes):
            for lbl in (*ax.get_xticklabels(), *ax.get_yticklabels()):
                lbl.set_fontfamily(_AR_FAMILY)
    fig.canvas.draw()  # finalise tick labels before styling rounds


def _style_axes(ax: plt.Axes) -> None:
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.grid(axis="y", color=_GRID, linewidth=0.8)
    ax.set_axisbelow(True)


# ── 1. follower growth line ──────────────────────────────────────────────────
def growth_chart(points: list[tuple[str, int]], lang: str = "ar",
                 username: str | None = None) -> io.BytesIO | None:
    """points: [(iso_datetime, followers), ...] — needs ≥2 points."""
    if not points or len(points) < 2:
        return None
    try:
        xs = [datetime.fromisoformat(p[0]) for p in points]
        ys = [float(p[1]) for p in points]
    except (ValueError, TypeError):
        return None

    fig, ax = plt.subplots(figsize=(9, 4.2), dpi=150, constrained_layout=True)
    ax.plot(xs, ys, color=_BRAND, linewidth=2.2, marker="o",
            markersize=3.5, markerfacecolor="white", markeredgecolor=_BRAND)
    ax.fill_between(xs, ys, min(ys) * 0.999, color=_BRAND, alpha=0.08)
    _style_axes(ax)

    title = _L(lang, "نمو المتابعين — 30 يوماً", "Follower growth — 30 days")
    if username:
        title += f"  @{username}"
    ax.set_title(title, fontsize=13, color=_INK, pad=12)
    ax.set_ylabel(_L(lang, "المتابعون", "Followers"), fontsize=10, color=_MUTE)
    ax.yaxis.set_major_formatter(
        plt.FuncFormatter(lambda v, _: f"{v/1e6:.1f}M" if v >= 1e6 else
                          (f"{v/1e3:.0f}K" if v >= 1e3 else f"{v:.0f}")))
    # NOTE: never use fig.autofmt_xdate() — it internally calls subplots_adjust,
    # which is incompatible with constrained_layout; rotate labels directly.
    for lbl in ax.get_xticklabels():
        lbl.set_rotation(30)
        lbl.set_ha("right")
        lbl.set_fontsize(8)
    _apply_style(fig, ax, lang)

    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return buf


# ── 2. posting heatmap (DOW × hour) ─────────────────────────────────────────
def posting_heatmap(videos: list[dict], lang: str = "ar") -> io.BytesIO | None:
    """videos: normalized video dicts (needs create_time + views)."""
    rows = [v for v in videos if v.get("create_time") and v.get("views")]
    if len(rows) < 3:
        return None
    matrix = np.full((7, 24), np.nan)
    buckets: dict[tuple[int, int], list[float]] = defaultdict(list)
    for v in rows:
        dt = datetime.fromtimestamp(int(v["create_time"]), tz=timezone.utc)
        buckets[(dt.weekday(), dt.hour)].append(float(v["views"]))
    for (d, h), vals in buckets.items():
        matrix[d, h] = float(np.mean(vals))

    fig, ax = plt.subplots(figsize=(10, 3.6), dpi=150, constrained_layout=True)
    masked = np.ma.masked_invalid(matrix)
    cmap = plt.cm.RdYlGn.copy()
    cmap.set_bad("#f5f5f5")
    im = ax.imshow(masked, aspect="auto", cmap=cmap)

    ax.set_xticks(range(24))
    ax.set_xticklabels([f"{h:02d}" for h in range(24)], fontsize=7)
    dow = DOW_AR if (lang or "ar") == "ar" and _AR_FAMILY else DOW_EN
    ax.set_yticks(range(7))
    ax.set_yticklabels([_ar(d) if lang == "ar" and _AR_FAMILY else d for d in dow],
                       fontsize=8)
    ax.set_title(_L(lang, "خريطة حرارية لأوقات النشر (متوسط المشاهدات)",
                     "Posting heatmap (avg views by day & hour)"),
                 fontsize=12, color=_INK, pad=10)
    cbar = fig.colorbar(im, ax=ax, shrink=0.85)
    cbar.ax.tick_params(labelsize=7)
    cbar.set_label(_L(lang, "مشاهدات", "Views"), fontsize=8)
    _apply_style(fig, ax, lang)

    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return buf


# ── 3. top hashtags bar ──────────────────────────────────────────────────────
def hashtags_bar(tags: list[tuple[str, int]], lang: str = "ar") -> io.BytesIO | None:
    tags = [(t_, c) for t_, c in (tags or []) if t_][:12]
    if len(tags) < 2:
        return None
    tags = tags[::-1]  # largest on top for barh
    labels = ["#" + t_ for t_, _ in tags]
    counts = [c for _, c in tags]

    fig, ax = plt.subplots(figsize=(8, max(2.4, 0.42 * len(tags))),
                           dpi=150, constrained_layout=True)
    bars = ax.barh(labels, counts, color=_BRAND, alpha=0.88, height=0.62)
    bars[-1].set_color(_BRAND2)  # top hashtag highlighted in cyan
    _style_axes(ax)
    ax.grid(axis="x", color=_GRID, linewidth=0.8)
    ax.grid(axis="y", visible=False)
    ax.set_title(_L(lang, "أكثر الهاشتاقات استخداماً", "Most used hashtags"),
                 fontsize=12, color=_INK, pad=10)
    ax.xaxis.set_major_formatter(
        plt.FuncFormatter(lambda v, _: f"{v/1e3:.0f}K" if v >= 1e3 else f"{v:.0f}"))
    ax.tick_params(axis="y", labelsize=9)
    for lbl in ax.get_yticklabels():
        lbl.set_color(_INK)
    _apply_style(fig, ax, lang)

    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return buf


# ── 4. engagement mix donut ──────────────────────────────────────────────────
def engagement_mix(videos: list[dict], lang: str = "ar") -> io.BytesIO | None:
    rows = [v for v in videos if v.get("views")]
    if len(rows) < 3:
        return None
    n = len(rows)
    vals = [sum(v.get("likes") or 0 for v in rows) / n,
            sum(v.get("comments") or 0 for v in rows) / n,
            sum(v.get("shares") or 0 for v in rows) / n,
            sum(v.get("bookmarks") or 0 for v in rows) / n]
    if sum(vals) <= 0:
        return None
    labels = [
        _L(lang, "إعجابات", "Likes"),
        _L(lang, "تعليقات", "Comments"),
        _L(lang, "مشاركات", "Shares"),
        _L(lang, "حفظ", "Saves"),
    ]
    colors = [_BRAND, _BRAND2, "#7c4dff", "#ffb300"]

    fig, ax = plt.subplots(figsize=(6.4, 4.6), dpi=150, constrained_layout=True)
    wedges, _, autotexts = ax.pie(
        vals, colors=colors, autopct="%1.1f%%", pctdistance=0.78,
        startangle=100, wedgeprops=dict(width=0.42, edgecolor="white"))
    for at in autotexts:
        at.set_fontsize(8)
        at.set_color("white")
    ax.legend(wedges, labels, loc="center left",
              bbox_to_anchor=(1.0, 0.5), frameon=False, fontsize=9)
    ax.set_title(_L(lang, "توزيع التفاعل لكل فيديو (متوسط)",
                     "Engagement mix per video (avg)"),
                 fontsize=12, color=_INK, pad=10)
    _apply_style(fig, ax, lang)

    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return buf


# ── 5. convenience bundle ────────────────────────────────────────────────────
def render_bundle(profile: dict, analytics: dict, lang: str = "ar"
                  ) -> dict[str, io.BytesIO]:
    """Render every chart that has enough data. Never raises."""
    out: dict[str, io.BytesIO] = {}
    try:
        growth = (analytics or {}).get("growth") or {}
        if growth.get("sufficient") and growth.get("points"):
            g = growth_chart(growth["points"], lang, profile.get("username"))
            if g:
                out["growth"] = g
        videos = profile.get("videos") or []
        h = posting_heatmap(videos, lang)
        if h:
            out["heatmap"] = h
        b = hashtags_bar((analytics or {}).get("top_hashtags"), lang)
        if b:
            out["hashtags"] = b
        m = engagement_mix(videos, lang)
        if m:
            out["engagement_mix"] = m
    except Exception as exc:  # noqa: BLE001 — charts are a nicety, never fatal
        log.warning("chart bundle failed: %s", exc)
    return out


def save_charts(profile: dict, analytics: dict, out_dir: str | Path,
                lang: str = "ar") -> list[Path]:
    """Write the bundle to out_dir; returns written paths."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, buf in render_bundle(profile, analytics, lang).items():
        path = out_dir / f"chart_{profile.get('username', 'user')}_{name}.png"
        path.write_bytes(buf.getvalue())
        written.append(path)
    return written


__all__ = ["growth_chart", "posting_heatmap", "hashtags_bar",
           "engagement_mix", "render_bundle", "save_charts"]
