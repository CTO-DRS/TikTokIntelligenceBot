"""
HTML report (Jinja2) — standalone styled page, RTL-aware, no external assets.
"""
from __future__ import annotations

from pathlib import Path

from bot.utils.i18n import t
from bot.utils.logger import get_logger

log = get_logger(__name__)

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"


class HTMLReport:
    def __init__(self, lang: str = "ar"):
        self.lang = lang if lang in {"ar", "en"} else "ar"

    def build(self, profile: dict, analytics: dict, out_path: Path) -> Path:
        from jinja2 import Environment, FileSystemLoader, select_autoescape

        env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)),
                          autoescape=select_autoescape(["html"]))
        template = env.get_template("report.html.j2")
        html = template.render(
            lang=self.lang,
            lang_dir="rtl" if self.lang == "ar" else "ltr",
            t=lambda key: t(self.lang, key),
            fmt_num=lambda n: f"{(n or 0):,}",
            profile=profile,
            analytics=analytics,
            videos=(profile.get("videos") or [])[:30],
            generated_at=profile.get("fetched_at", ""),
        )
        out_path.write_text(html, encoding="utf-8")
        return out_path
