"""
Analytics engine — every number here is computed from PUBLIC video/profile data.

Honesty rules:
* engagement rate, averages, best posting time, hashtags, keywords, content
  mix  → DERIVED (computed, clearly labelled).
* fake-follower ratio → low-confidence heuristic, always labelled.
* audience age/gender/geo split and fan-vs-non-fan views → UNAVAILABLE
  (visible only to the account owner inside TikTok analytics).
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone

from bot.utils.logger import get_logger

log = get_logger(__name__)

DOW_EN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DOW_AR = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]

AR_STOPWORDS = {
    "في", "من", "على", "عن", "الى", "إلى", "هذا", "هذه", "ذلك", "التي", "الذي",
    "مع", "كان", "كانت", "هو", "هي", "ما", "لا", "و", "أو", "ثم", "قد", "كل",
    "بعد", "قبل", "بين", "عند", "لكن", "حتى", "أن", "إن", "لازم", "اليوم",
}
EN_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of",
    "with", "is", "are", "was", "were", "be", "been", "this", "that", "it",
    "as", "by", "from", "you", "your", "i", "we", "they", "he", "she", "do",
    "not", "so", "if", "my", "me", "just", "get", "got", "how", "what",
}

CONTENT_CATEGORIES: dict[str, re.Pattern] = {
    "education": re.compile(r"(تعلم|شرح|درس|طريقة|كيف|learn|tutorial|how|tips)", re.I),
    "entertainment": re.compile(r"(فيد|ضحك|كوميدي|تحدي|funny|comedy|challenge|prank)", re.I),
    "tech": re.compile(r"(تقنية|برمجة|جوال|ايفون|اندرويد|tech|coding|phone|ai)", re.I),
    "fashion": re.compile(r"(موضة|فاشن|ملابس|مكياج|fashion|makeup|outfit|style)", re.I),
    "food": re.compile(r"(طبخ|وصفة|اكل|مطعم|food|recipe|cook|eat)", re.I),
    "sports": re.compile(r"(كرة|رياضة|هداف|لياقة|sport|football|gym|workout)", re.I),
    "music": re.compile(r"(اغنية|موسيقى|غناء|song|music|sing|cover)", re.I),
    "vlog": re.compile(r"(فلوق|يوميات|رحلة|سفر|vlog|daily|travel|trip)", re.I),
}


class EngagementAnalyzer:
    @staticmethod
    def summarize(profile: dict) -> dict:
        videos: list[dict] = profile.get("videos") or []
        followers = profile.get("followers") or 0
        n = len(videos)
        out: dict = {
            "videos_analyzed": n,
            "avg_views": None, "avg_likes": None, "avg_comments": None,
            "avg_shares": None, "engagement_rate": None, "er_basis": None,
            "total_views": None,
        }
        if not n:
            out["er_basis"] = "no public videos"
            return out
        avg = lambda k: sum(int(v.get(k) or 0) for v in videos) / n  # noqa: E731
        out.update({
            "avg_views": avg("views"), "avg_likes": avg("likes"),
            "avg_comments": avg("comments"), "avg_shares": avg("shares"),
            "total_views": sum(int(v.get("views") or 0) for v in videos),
        })
        if followers > 0:
            out["engagement_rate"] = round(
                (out["avg_likes"] + out["avg_comments"] + out["avg_shares"]) / followers * 100, 3)
            out["er_basis"] = "per follower"
        elif out["avg_views"]:
            out["engagement_rate"] = round(
                (out["avg_likes"] + out["avg_comments"] + out["avg_shares"]) / out["avg_views"] * 100, 3)
            out["er_basis"] = "per view (follower count hidden)"
        return out


class ContentAnalyzer:
    @staticmethod
    def best_posting_hours(videos: list[dict], top: int = 5) -> list[dict]:
        """Grid weekday×hour scored by average views (needs create_time)."""
        buckets: dict[tuple[int, int], tuple[int, int]] = {}
        for v in videos:
            ts = v.get("create_time")
            if not ts:
                continue
            try:
                dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
            except (TypeError, ValueError, OverflowError):
                continue
            key = (dt.weekday(), dt.hour)
            views = int(v.get("views") or 0)
            total, count = buckets.get(key, (0, 0))
            buckets[key] = (total + views, count + 1)
        scored = [
            {"weekday": wd, "hour": hr, "avg_views": total / count, "samples": count}
            for (wd, hr), (total, count) in buckets.items() if count
        ]
        scored.sort(key=lambda x: x["avg_views"], reverse=True)
        return scored[:top]

    @staticmethod
    def hashtag_analysis(videos: list[dict], top: int = 12) -> list[tuple[str, int]]:
        counter: Counter[str] = Counter()
        for v in videos:
            for tag in v.get("hashtags") or []:
                if tag:
                    counter[tag.lower()] += 1
        return counter.most_common(top)

    @staticmethod
    def keyword_extraction(videos: list[dict], top: int = 12) -> list[tuple[str, int]]:
        counter: Counter[str] = Counter()
        for v in videos:
            words = re.findall(r"[\u0600-\u06FFa-zA-Z]{3,}", v.get("desc") or "")
            for w in words:
                lw = w.lower()
                if lw in EN_STOPWORDS or w in AR_STOPWORDS:
                    continue
                counter[w if any("\u0600" <= c <= "\u06FF" for c in w) else lw] += 1
        return counter.most_common(top)

    @staticmethod
    def classify_content(videos: list[dict]) -> dict[str, int]:
        mixes: Counter[str] = Counter()
        for v in videos:
            text = (v.get("desc") or "") + " " + " ".join(v.get("hashtags") or [])
            matched = False
            for cat, rx in CONTENT_CATEGORIES.items():
                if rx.search(text):
                    mixes[cat] += 1
                    matched = True
            if not matched:
                mixes["other"] += 1
        return dict(mixes.most_common())

    @staticmethod
    def music_analysis(videos: list[dict], top: int = 8) -> list[dict]:
        counter: Counter[str] = Counter()
        for v in videos:
            title = v.get("music_title")
            if title:
                counter[f"{title} — {v.get('music_author') or '?'}"] += 1
        return [{"track": k, "count": n} for k, n in counter.most_common(top)]


class FollowerAnalytics:
    @staticmethod
    def growth_30d(snapshots: list) -> dict:
        """snapshots: AccountSnapshot rows ordered by captured_at."""
        if len(snapshots) < 2:
            return {"sufficient": False, "points": [], "delta_30d": None,
                    "note": "needs ≥2 snapshots over time — enable /track to build history"}
        points = [(s.captured_at.isoformat(), s.followers) for s in snapshots]
        delta = int(snapshots[-1].followers - snapshots[0].followers)
        return {"sufficient": True, "points": points, "delta_30d": delta, "note": ""}

    @staticmethod
    def fake_follower_estimate(profile: dict) -> dict:
        """
        Low-confidence heuristic ONLY:
        accounts whose views-per-follower is extremely low vs likes ratio
        anomaly often indicates inactive/bought followers. Range, not truth.
        """
        followers = profile.get("followers") or 0
        videos = profile.get("videos") or []
        if followers < 1000 or len(videos) < 5:
            return {"low": None, "high": None, "confidence": "unavailable",
                    "note": "insufficient public data"}
        avg_views = sum(int(v.get("views") or 0) for v in videos) / len(videos)
        ratio = avg_views / followers
        if ratio >= 0.35:
            low, high = 0, 8
        elif ratio >= 0.15:
            low, high = 5, 20
        elif ratio >= 0.05:
            low, high = 15, 40
        else:
            low, high = 35, 70
        return {"low": low, "high": high, "confidence": "low",
                "note": "heuristic from public view/follower ratio — not a verdict"}


class AudienceAnalytics:
    """Honest audience section — most splits are owner-only analytics."""

    @staticmethod
    def audience(profile: dict) -> dict:
        return {
            "geo_split": None, "age_split": None, "gender_split": None,
            "fan_vs_nonfan_views": None,
            "note": "audience splits are visible only to the account owner inside TikTok analytics",
            "fake_estimate": FollowerAnalytics.fake_follower_estimate(profile),
        }


class CompareService:
    ROWS = [
        ("followers", "f_followers"), ("following", "f_following"),
        ("likes", "f_likes"), ("videos_count", "f_videos"),
        ("avg_views", "f_avg_views"), ("engagement_rate", "f_engagement"),
    ]

    @staticmethod
    def diff(a: dict, b: dict) -> list[tuple[str, str, str]]:
        eng_a = EngagementAnalyzer.summarize(a)
        eng_b = EngagementAnalyzer.summarize(b)
        rows: list[tuple[str, str, str]] = [
            ("@username", str(a.get("username")), str(b.get("username"))),
            ("verified", "✅" if a.get("verified") else "—", "✅" if b.get("verified") else "—"),
            ("private", "✅" if a.get("private") else "—", "✅" if b.get("private") else "—"),
        ]
        for key, label in (("followers", "followers"), ("following", "following"),
                           ("likes", "likes"), ("videos_count", "videos")):
            rows.append((label, f"{a.get(key) or 0:,}", f"{b.get(key) or 0:,}"))
        rows.append(("avg_views", f"{(eng_a.get('avg_views') or 0):,.0f}",
                     f"{(eng_b.get('avg_views') or 0):,.0f}"))
        rows.append(("engagement_%", f"{(eng_a.get('engagement_rate') or 0):.2f}",
                     f"{(eng_b.get('engagement_rate') or 0):.2f}"))
        return rows


class AnalyticsEngine:
    """Facade used by handlers: profile → full analytics dict."""

    def __init__(self, snapshots: list | None = None):
        self._snapshots = snapshots or []

    def analyze(self, profile: dict) -> dict:
        videos = profile.get("videos") or []
        engagement = EngagementAnalyzer.summarize(profile)
        result = {
            **engagement,
            "best_hours": ContentAnalyzer.best_posting_hours(videos),
            "top_hashtags": ContentAnalyzer.hashtag_analysis(videos),
            "keywords": ContentAnalyzer.keyword_extraction(videos),
            "categories": ContentAnalyzer.classify_content(videos),
            "music": ContentAnalyzer.music_analysis(videos),
            "audience": AudienceAnalytics.audience(profile),
            "growth": FollowerAnalytics.growth_30d(self._snapshots),
        }
        # flatten for formatters
        profile["avg_views"] = engagement.get("avg_views")
        profile["total_views"] = engagement.get("total_views")
        profile["engagement_rate"] = engagement.get("engagement_rate")
        profile["top_hashtags"] = result["top_hashtags"]
        return result


__all__ = ["AnalyticsEngine", "EngagementAnalyzer", "ContentAnalyzer",
           "FollowerAnalytics", "AudienceAnalytics", "CompareService",
           "DOW_AR", "DOW_EN"]
