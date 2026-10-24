"""
PDF report (ReportLab) with Arabic RTL support.

Arabic shaping: reportlab does not shape Arabic, so every Arabic string passes
through `arabic_reshaper` (joins letters) + `python-bidi` (visual reorder).
Fonts: searches common Noto Naskh Arabic paths (installed by the Dockerfile);
falls back to Helvetica for pure-English reports.
"""
from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path

from bot.utils.logger import get_logger
from bot.utils.i18n import t

log = get_logger(__name__)

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoNaskhArabic.ttf",
    "/usr/share/fonts/truetype/noto-naskh-arabic/NotoNaskhArabic-Regular.ttf",
    "/usr/share/fonts/truetype/arabic/NotoNaskhArabic-Regular.ttf",
]
FONT_BOLD_CANDIDATES = [
    "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Bold.ttf",
    "/usr/share/fonts/truetype/noto-naskh-arabic/NotoNaskhArabic-Bold.ttf",
]


class PDFReport:
    def __init__(self, lang: str = "ar"):
        self.lang = lang if lang in {"ar", "en"} else "ar"
        self._reshaper = None
        self._bidi = None
        if self.lang == "ar":
            try:
                import arabic_reshaper
                from bidi.algorithm import get_display

                self._reshaper = arabic_reshaper.ArabicReshaper()
                self._bidi = get_display
            except ImportError:
                log.warning("arabic_reshaper/bidi missing — Arabic will render unshaped")

    # ── text shaping ─────────────────────────────────────────
    def _ar(self, text: str) -> str:
        if self.lang == "ar" and self._reshaper and self._bidi:
            return self._bidi(self._reshaper.reshape(text))
        return text

    # ── fonts ────────────────────────────────────────────────
    def _register_fonts(self):
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        regular = next((p for p in FONT_CANDIDATES if Path(p).exists()), None)
        bold = next((p for p in FONT_BOLD_CANDIDATES if Path(p).exists()), None)
        if regular:
            pdfmetrics.registerFont(TTFont("Arabic", regular))
            pdfmetrics.registerFont(TTFont("Arabic-Bold", bold or regular))
            return "Arabic", "Arabic-Bold"
        return "Helvetica", "Helvetica-Bold"

    # ── charts ───────────────────────────────────────────────
    def _chart(self, labels: list[str], values: list, title: str) -> io.BytesIO | None:
        if not values or all(v is None for v in values):
            return None
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(7, 2.8), constrained_layout=True)
        ax.plot(range(len(values)), values, marker="o", linewidth=1.6, color="#e0245e")
        ax.set_title(title, fontsize=10)
        step = max(1, len(labels) // 6)
        ax.set_xticks(range(0, len(labels), step))
        ax.set_xticklabels(labels[::step], rotation=30, fontsize=7)
        ax.grid(alpha=0.3)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=130)
        plt.close(fig)
        buf.seek(0)
        return buf

    # ── main builder ─────────────────────────────────────────
    def build(self, profile: dict, analytics: dict, out_path: Path) -> Path:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_RIGHT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
        )

        font, font_bold = self._register_fonts()
        rtl = self.lang == "ar"
        body = ParagraphStyle("body", fontName=font, fontSize=10, leading=15,
                              alignment=TA_RIGHT if rtl else 0)
        h1 = ParagraphStyle("h1", fontName=font_bold, fontSize=17, leading=22,
                            alignment=TA_RIGHT if rtl else 0, spaceAfter=6)
        h2 = ParagraphStyle("h2", fontName=font_bold, fontSize=12.5, leading=17,
                            textColor=colors.HexColor("#c2185b"),
                            alignment=TA_RIGHT if rtl else 0, spaceBefore=10, spaceAfter=4)

        doc = SimpleDocTemplate(str(out_path), pagesize=A4,
                                leftMargin=16 * mm, rightMargin=16 * mm,
                                topMargin=14 * mm, bottomMargin=14 * mm,
                                title=f"TikTok Intelligence Report @{profile.get('username')}")
        story: list = []

        # cover header
        story.append(Paragraph(self._ar("تقرير استخبارات تيك توك" if rtl else "TikTok Intelligence Report"), h1))
        story.append(Paragraph(
            self._ar(f"@{profile.get('username')} — {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"),
            body))
        if profile.get("demo"):
            story.append(Paragraph(self._ar("⚠ وضع تجريبي — بيانات مُصنّعة للتوضيح" if rtl
                                            else "⚠ DEMO DATA — synthetic sample"), body))
        story.append(Spacer(1, 6))

        # identity + stats table
        ident_rows: list[list[str]] = []
        eng = analytics or {}

        def row(label_key: str, value: str) -> None:
            ident_rows.append([self._ar(t(self.lang, label_key)), value])

        row("f_name", str(profile.get("nickname") or "—"))
        row("f_user_id", str(profile.get("id") or t(self.lang, "na")))
        row("f_verified", "✅" if profile.get("verified") else "—")
        row("f_private", "✅" if profile.get("private") else "—")
        row("f_region", str(profile.get("region") or t(self.lang, "na")))
        row("f_followers", f"{profile.get('followers') or 0:,}")
        row("f_following", f"{profile.get('following') or 0:,}")
        row("f_likes", f"{profile.get('likes') or 0:,}")
        row("f_videos", f"{profile.get('videos_count') or 0:,}")
        row("f_avg_views", f"{(eng.get('avg_views') or 0):,.0f}")
        er = eng.get("engagement_rate")
        row("f_engagement", f"{er:.2f}%" if er else t(self.lang, "na"))

        tbl = Table(ident_rows, colWidths=[60 * mm, 100 * mm])
        tbl.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), font),
            ("FONTNAME", (0, 0), (0, -1), font_bold),
            ("FONTSIZE", (0, 0), (-1, -1), 9.5),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#dddddd")),
            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#fdf2f6")),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(Paragraph(self._ar(t(self.lang, "sec_identity")), h2))
        story.append(tbl)

        # growth chart (needs snapshots)
        growth = (eng.get("growth") or {})
        points = growth.get("points") or []
        if growth.get("sufficient") and len(points) >= 2:
            labels = [p[0][:10] for p in points]
            values = [p[1] for p in points]
            buf = self._chart(labels, values, self._ar(t(self.lang, "f_growth")))
            if buf:
                story.append(Paragraph(self._ar(t(self.lang, "sec_stats")), h2))
                story.append(Image(buf, width=170 * mm, height=68 * mm))
        story.append(PageBreak())

        # top videos table
        videos = profile.get("videos") or []
        if videos:
            head = ["#", t(self.lang, "view_video"), "❤", "💬", "🔁", "⏱"]
            head_ar = [self._ar(x) if not x.isdigit() else x for x in head]
            data = [head_ar]
            for i, v in enumerate(videos[:15], 1):
                data.append([
                    str(i), f"{v.get('views') or 0:,}", f"{v.get('likes') or 0:,}",
                    f"{v.get('comments') or 0:,}", f"{v.get('shares') or 0:,}",
                    f"{v.get('duration') or '—'}",
                ])
            vt = Table(data, colWidths=[10 * mm, 34 * mm, 30 * mm, 30 * mm, 30 * mm, 20 * mm])
            vt.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (-1, -1), font),
                ("FONTNAME", (0, 0), (-1, 0), font_bold),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#dddddd")),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#fce4ec")),
            ]))
            story.append(Paragraph(self._ar(t(self.lang, "sec_content")), h2))
            story.append(vt)

            # hashtags / keywords
            tags = eng.get("top_hashtags") or []
            if tags:
                story.append(Paragraph(
                    self._ar(t(self.lang, "f_top_hashtags") + ": " +
                             " ".join("#" + tag for tag, _ in tags[:12])), body))
            kws = eng.get("keywords") or []
            if kws:
                story.append(Paragraph(
                    self._ar(t(self.lang, "f_keywords") + ": " +
                             " ".join(f"{w}({n})" for w, n in kws[:10])), body))

        # geo / device honesty section
        story.append(Paragraph(self._ar(t(self.lang, "sec_geo") + " / " + t(self.lang, "sec_device")), h2))
        story.append(Paragraph(self._ar(t(self.lang, "privacy_note")), body))
        sec = profile.get("security") or {}
        if sec.get("score") is not None:
            story.append(Paragraph(
                self._ar(f"{t(self.lang, 'security_score')}: {sec['score']}/100"), body))

        # footer disclaimer
        story.append(Spacer(1, 14))
        story.append(Paragraph(self._ar(
            "أُنتج هذا التقرير من بيانات عامة فقط — لا يحتوي على أي بيانات مخترقة أو خاصة."
            if rtl else
            "Generated from public data only — no private or breached data is included."), body))

        doc.build(story)
        return out_path
