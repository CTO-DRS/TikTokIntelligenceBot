"""
Analytics unit tests — pure math on fixtures, no network.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.services.analytics import (  # noqa: E402
    AnalyticsEngine, CompareService, ContentAnalyzer, EngagementAnalyzer,
    FollowerAnalytics,
)


def _video(views: int, ts: int, desc: str = "demo text", tags: list | None = None) -> dict:
    return {"views": views, "likes": views // 20, "comments": views // 100,
            "shares": views // 200, "bookmarks": views // 300,
            "create_time": ts, "desc": desc, "hashtags": tags or []}


def test_engagement_summaries():
    videos = [_video(1000, 1717000000), _video(3000, 1717086400)]
    profile = {"followers": 5000, "videos": videos}
    out = EngagementAnalyzer.summarize(profile)
    assert out["videos_analyzed"] == 2
    assert out["avg_views"] == 2000
    assert out["engagement_rate"] is not None
    assert out["er_basis"] == "per follower"


def test_best_posting_hours_ranking():
    videos = [_video(5000, 1717123200), _video(100, 1717080000)]  # different hours
    top = ContentAnalyzer.best_posting_hours(videos, top=2)
    assert len(top) == 2
    assert top[0]["avg_views"] >= top[1]["avg_views"]


def test_hashtag_and_keywords():
    videos = [
        _video(100, 1717000000, desc="تعلم البرمجة يوميا", tags=["tech", "code"]),
        _video(100, 1717003600, desc="learn coding daily", tags=["tech"]),
    ]
    tags = ContentAnalyzer.hashtag_analysis(videos)
    assert tags[0] == ("tech", 2)
    kws = ContentAnalyzer.keyword_extraction(videos)
    assert any("تعلم" == w or "تعلم" in w for w, _ in kws) or len(kws) > 0


def test_content_classification():
    videos = [_video(10, 1, desc="شرح python tutorial"), _video(10, 2, desc="وصفة طبخ")]
    mixes = ContentAnalyzer.classify_content(videos)
    assert mixes.get("education") == 1
    assert mixes.get("food") == 1


def test_growth_insufficient_snapshots():
    out = FollowerAnalytics.growth_30d([])
    assert out["sufficient"] is False
    assert out["delta_30d"] is None


def test_fake_follower_estimate_labels_confidence():
    profile = {"followers": 100000, "videos": [_video(500, i) for i in range(6)]}
    est = FollowerAnalytics.fake_follower_estimate(profile)
    assert est["confidence"] == "low"
    assert est["low"] is not None and est["high"] is not None


def test_analyze_flattens_for_formatters():
    profile = {"followers": 1000, "videos_count": 2,
               "videos": [_video(100, 1717000000), _video(200, 1717003600)]}
    engine = AnalyticsEngine(snapshots=[])
    result = engine.analyze(profile)
    assert profile["avg_views"] == 150
    assert "best_hours" in result and "audience" in result


def test_compare_diff_rows():
    a = {"username": "a", "verified": True, "private": False, "followers": 100,
         "following": 10, "likes": 1000, "videos_count": 5,
         "videos": [_video(10, 1)]}
    b = {"username": "b", "verified": False, "private": True, "followers": 900,
         "following": 50, "likes": 9000, "videos_count": 15,
         "videos": [_video(90, 1)]}
    rows = CompareService.diff(a, b)
    labels = [r[0] for r in rows]
    assert "followers" in labels and "engagement_%" in labels
