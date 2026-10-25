"""
Canonical JSON report generator — the machine-readable export format.

Structure contract (versioned):
{
  "report_version": "1.1",
  "generator": "TikTokIntelligenceBot",
  "generated_at": "<iso-utc>",
  "honesty_legend": {...},          # explains status markers
  "profile": {...},                 # normalized profile (videos split out)
  "videos": [...],                  # last N videos (normalized)
  "analytics": {...},               # AnalyticsEngine.analyze() output
  "data_integrity": {               # quick machine-readable availability tally
      "available_fields": int, "estimated_fields": int, "unavailable_fields": int
  }
}

The ``profile.meta`` map (when present) carries per-field
``{"status": available|estimated|unavailable, "confidence": ..., "reason": ...}``
so downstream consumers can honour the data-honesty contract programmatically.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

REPORT_VERSION = "1.1"

HONESTY_LEGEND = {
    "available": "real public data fetched at scan time",
    "estimated": "statistical model over public data — see confidence",
    "unavailable": "server-side/private data; no public API exists — never fabricated",
}


def _jsonable(obj: object) -> object:
    """Recursively convert anything json-incompatible into strings."""
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (int, float, str, bool)) or obj is None:
        return obj
    if isinstance(obj, Path):
        return str(obj)
    if hasattr(obj, "isoformat"):  # datetime
        return obj.isoformat()
    return str(obj)


def _tally(meta: dict) -> dict[str, int]:
    counts = {"available": 0, "estimated": 0, "unavailable": 0}
    for entry in (meta or {}).values():
        if isinstance(entry, dict):
            status = str(entry.get("status", "")).lower()
            if status in counts:
                counts[status] += 1
    return {"available_fields": counts["available"],
            "estimated_fields": counts["estimated"],
            "unavailable_fields": counts["unavailable"]}


class JSONReport:
    """Stateless generator — kept class-shaped for parity with PDF/HTML/Excel."""

    def to_dict(self, profile: dict, analytics: dict) -> dict:
        profile = dict(profile or {})
        videos = profile.pop("videos", None) or []
        meta = profile.get("meta") or {}
        return {
            "report_version": REPORT_VERSION,
            "generator": "TikTokIntelligenceBot",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "honesty_legend": HONESTY_LEGEND,
            "profile": _jsonable(profile),
            "videos": _jsonable(videos[:30]),
            "analytics": _jsonable(analytics or {}),
            "data_integrity": _tally(meta),
        }

    def build(self, profile: dict, analytics: dict, out_path: str | Path) -> Path:
        """Write the canonical JSON report. Never raises on partial data."""
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        payload = self.to_dict(profile, analytics)
        out_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8")
        return out_path


__all__ = ["JSONReport", "REPORT_VERSION", "HONESTY_LEGEND"]
