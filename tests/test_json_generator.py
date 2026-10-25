"""
JSON report generator tests — canonical structure, honesty tally, robustness.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reports.generators.json_generator import (  # noqa: E402
    HONESTY_LEGEND, REPORT_VERSION, JSONReport,
)


def _profile() -> dict:
    return {
        "username": "demo_user", "nickname": "Demo", "followers": 1200,
        "hearts": 34000, "region": "SA", "private": False,
        "videos": [{"id": "1", "views": 100, "likes": 10}] * 2,
        "meta": {
            "username": {"status": "available", "confidence": None, "reason": None},
            "followers": {"status": "available", "confidence": None, "reason": None},
            "device_id": {"status": "unavailable", "confidence": None,
                          "reason": "server-side private data"},
            "audience_geo": {"status": "estimated", "confidence": "low",
                             "reason": None},
        },
    }


def test_structure_and_version():
    out = JSONReport().to_dict(_profile(), {"engagement_rate": 4.2})
    assert out["report_version"] == REPORT_VERSION
    assert out["generator"] == "TikTokIntelligenceBot"
    assert out["honesty_legend"] == HONESTY_LEGEND
    assert set(out) == {"report_version", "generator", "generated_at",
                        "honesty_legend", "profile", "videos", "analytics",
                        "data_integrity"}
    # videos split out of profile
    assert "videos" not in out["profile"]
    assert len(out["videos"]) == 2


def test_data_integrity_tally():
    out = JSONReport().to_dict(_profile(), {})
    assert out["data_integrity"] == {"available_fields": 2,
                                     "estimated_fields": 1,
                                     "unavailable_fields": 1}


def test_build_writes_valid_json_file(tmp_path):
    path = tmp_path / "nested" / "report.json"
    result = JSONReport().build(_profile(), {"avg_views": 100}, path)
    assert result == path
    parsed = json.loads(path.read_text(encoding="utf-8"))
    assert parsed["profile"]["username"] == "demo_user"
    assert parsed["analytics"]["avg_views"] == 100
    datetime.fromisoformat(parsed["generated_at"])  # parses fine


def test_jsonable_conversions(tmp_path):
    profile = {"username": "x", "videos": [], "when": datetime(2026, 1, 1),
               "nested": {"set_like": [1, (2, 3)]}, "meta": {}}
    out = JSONReport().to_dict(profile, {})
    json.dumps(out)  # must not raise
    assert out["profile"]["when"] == "2026-01-01T00:00:00"


def test_robust_to_empty_inputs(tmp_path):
    path = tmp_path / "r.json"
    JSONReport().build({}, None, path)
    parsed = json.loads(path.read_text(encoding="utf-8"))
    assert parsed["data_integrity"]["available_fields"] == 0
    assert parsed["videos"] == []
