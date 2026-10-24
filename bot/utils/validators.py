"""Input validation, sanitisation (anti-XSS) and injection detection (IDS)."""
from __future__ import annotations

import html
import re

USERNAME_RE = re.compile(r"^[A-Za-z0-9._]{2,30}$")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?:\+?\d{1,3}[\s\-]?)?(?:\(?\d{3,4}\)?[\s\-]?){2}\d{3,4}")
TELEGRAM_URL_USER_RE = re.compile(r"(?:tiktok\.com/@|@)([A-Za-z0-9._]{2,30})")

# Patterns that should never appear in user-controlled input reaching storage
INJECTION_PATTERNS = re.compile(
    r"(\bunion\b.+\bselect\b|\bselect\b.+\bfrom\b|\bdrop\s+table|\binsert\s+into\b|"
    r"\bdelete\s+from\b|--\s|;/\*|<script|javascript:|onerror\s*=|onload\s*=|"
    r"\.\./\.\.|\bexec\s*\(|\bwaitfor\s+delay\b)",
    re.IGNORECASE,
)


def clean_username(raw: str | None) -> str | None:
    """Accept '@user', 'https://tiktok.com/@user' or 'user' → validated username."""
    if not raw:
        return None
    text = raw.strip()
    for prefix in ("https://www.tiktok.com/@", "https://tiktok.com/@",
                   "http://www.tiktok.com/@", "http://tiktok.com/@", "www.tiktok.com/@", "@"):
        if text.lower().startswith(prefix.lower()):
            text = text[len(prefix):]
            break
    text = text.split("/")[0].split("?")[0].strip()
    if TELEGRAM_URL_USER_RE.fullmatch(text) and not USERNAME_RE.fullmatch(text):
        return None
    return text if USERNAME_RE.fullmatch(text) else None


def sanitize_text(text: str | None, limit: int = 3500) -> str:
    """HTML-escape untrusted text before it is embedded in Telegram HTML."""
    if not text:
        return ""
    return html.escape(str(text))[:limit]


def detect_injection(payload: str | None) -> bool:
    """Return True when the payload matches known SQLi/XSS/path-traversal patterns."""
    if not payload:
        return False
    return bool(INJECTION_PATTERNS.search(payload))


def extract_emails(text: str | None) -> list[str]:
    """Public contact emails the owner voluntarily wrote in their own bio."""
    if not text:
        return []
    return sorted(set(EMAIL_RE.findall(text)))[:5]


def extract_phones(text: str | None) -> list[str]:
    """Public phone numbers found in the bio (best-effort heuristic)."""
    if not text:
        return []
    found = []
    for match in PHONE_RE.findall(text):
        digits = re.sub(r"\D", "", match)
        if 9 <= len(digits) <= 15:
            found.append(match.strip())
    return sorted(set(found))[:3]


def safe_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._\-]", "_", name)[:80] or "file"
