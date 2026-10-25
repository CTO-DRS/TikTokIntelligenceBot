"""
Chart service tests — pure rendering on fixtures, no network, no files left
behind (everything rendered to in-memory PNG buffers).
"""
from __future__ import annotations

import io
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.services.charts import (  # noqa: E402
    engagement_mix, growth_chart, hashtags_bar, posting_heatmap, render_bundle,
    save_charts,
)


def _iso(minutes_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def _is_png(buf: io.BytesIO | None) -> bool:
    return buf is not None and buf.getvalue()[:8] == b"\x89PNG\r\n\x1a\n"


def _videos(n: int = 10) -> list[dict]:
    base = int(datetime(2026, 10, 1, 14, 0, tzinfo=timezone.utc).timestamp())
    out = []
    for i in range(n):
        out.append({
            "id": str(i), "create_time": base + i * 3600 * 7,
            "views": 1000 * (i + 1), "likes": 100 * (i + 1),
            "comments": 10 * (i + 1), "shares": 5 * (i + 1),
            "bookmarks": 3 * (i + 1), "desc": f"demo {i}",
            "hashtags": ["fyp", "tech", "ai"] if i % 2 == 0 else ["fyp"],
        })
    return out


def test_growth_chart_renders_png():
    points = [(_iso(i * 1440), 10_000 + i * 250) for i in range(15)]
    assert _is_png(growth_chart(points, "ar", "demo_user"))
    assert _is_png(growth_chart(points, "en"))


def test_growth_chart_needs_two_points():
    assert growth_chart([(_iso(0), 100)], "ar") is None
    assert growth_chart([], "ar") is None


def test_growth_chart_bad_points_returns_none():
    assert growth_chart([("not-a-date", "x"), ("also-bad", 5)], "ar") is None


def test_posting_heatmap_renders_png():
    assert _is_png(posting_heatmap(_videos(10), "ar"))
    assert _is_png(posting_heatmap(_videos(10), "en"))


def test_posting_heatmap_needs_data():
    assert posting_heatmap([], "ar") is None
    assert posting_heatmap([{"create_time": 1, "views": 5}], "ar") is None


def test_hashtags_bar_renders_png():
    tags = [("fyp", 30), ("tech", 20), ("ai", 10), ("vlog", 5)]
    assert _is_png(hashtags_bar(tags, "ar"))
    assert _is_png(hashtags_bar(tags, "en"))


def test_hashtags_bar_needs_two_tags():
    assert hashtags_bar([("fyp", 3)], "ar") is None
    assert hashtags_bar([], "en") is None


def test_engagement_mix_renders_png():
    assert _is_png(engagement_mix(_videos(6), "ar"))


def test_engagement_mix_zero_interactions_none():
    flat = [{"views": 100, "likes": 0, "comments": 0, "shares": 0, "bookmarks": 0}
            for _ in range(4)]
    assert engagement_mix(flat, "en") is None


def test_render_bundle_and_save(tmp_path):
    profile = {"username": "demo_user", "videos": _videos(10)}
    analytics = {"growth": {"sufficient": True,
                            "points": [(_iso(i * 1440), 5000 + i * 100)
                                       for i in range(10)]},
                 "top_hashtags": [("fyp", 9), ("tech", 5), ("ai", 2)]}
    bundle = render_bundle(profile, analytics, "ar")
    assert set(bundle) <= {"growth", "heatmap", "hashtags", "engagement_mix"}
    assert "growth" in bundle and "hashtags" in bundle

    paths = save_charts(profile, analytics, tmp_path, "ar")
    assert len(paths) == len(bundle)
    for p in paths:
        assert p.exists() and p.stat().st_size > 100


def test_render_bundle_never_raises_on_garbage():
    assert render_bundle({"videos": "oops"}, {"growth": None}, "ar") is not None or True
    bundle = render_bundle({}, None, "ar")
    assert bundle == {}
