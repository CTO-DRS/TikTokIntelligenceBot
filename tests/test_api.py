"""
Unit tests for the TikTok collector parsing (no network access).

The fixture mimics the `__UNIVERSAL_DATA_FOR_REHYDRATION__` JSON blob that
tiktok.com embeds in every public profile page.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.services.tiktok_api import TikTokClient, bulk_fetch  # noqa: E402

SAMPLE_HTML = """
<html><body>
<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">__JSON__</script>
</body></html>
"""

USER_INFO = {
    "user": {
        "id": "7001122334455667788",
        "uniqueId": "sample_creator",
        "secUid": "AQ123secuid",
        "nickname": "Sample Creator",
        "signature": "Content about tech ✉️ hello@sample.dev IG: @sample",
        "avatarLarger": "https://example.com/avatar.jpg",
        "verified": True,
        "privateAccount": False,
        "bioLink": {"link": "https://instagram.com/sample"},
        "region": "SA",
        "language": "ar",
    },
    "stats": {
        "followerCount": 150000,
        "followingCount": 321,
        "heartCount": 2400000,
        "videoCount": 187,
    },
}


def _video(i: int) -> dict:
    return {
        "id": f"vid{i}",
        "createTime": 1717000000 + i * 3600,
        "video": {"duration": 21},
        "stats": {"playCount": 10000 + i, "diggCount": 900 + i,
                  "commentCount": 40 + i, "shareCount": 12 + i, "collectCount": 30 + i},
        "desc": f"video number {i} #tech #fyp",
        "textExtra": [{"hashtagName": "tech"}, {"hashtagName": "fyp"}],
        "music": {"title": "Cool Track", "authorName": "Producer One"},
        "locationCreated": None,
    }


def _sample_html() -> str:
    blob = {"__DEFAULT_SCOPE__": {"webapp.user-detail": {
        "userInfo": USER_INFO,
        "itemList": [_video(i) for i in range(10)],
    }}}
    return SAMPLE_HTML.replace("__JSON__", json.dumps(blob))


def test_extract_profile_fields():
    parsed = TikTokClient.extract_from_html(_sample_html())
    assert parsed is not None
    p = parsed["profile"]
    assert p["username"] == "sample_creator"
    assert p["followers"] == 150000
    assert p["verified"] is True and p["private"] is False
    assert p["region"] == "SA"
    assert len(parsed["videos"]) == 10


def test_video_normalization():
    parsed = TikTokClient.extract_from_html(_sample_html())
    v = parsed["videos"][0]
    assert v["views"] == 10000
    assert v["likes"] == 900
    assert v["duration"] == 21
    assert "tech" in v["hashtags"]
    assert v["music_title"] == "Cool Track"


def test_bio_contact_extraction():
    parsed = TikTokClient.extract_from_html(_sample_html())
    p = parsed["profile"]
    assert p["emails"] == ["hello@sample.dev"]
    assert p["socials"].get("instagram") == "sample"


def test_universal_data_missing_returns_none():
    assert TikTokClient.extract_from_html("<html><body>challenge page</body></html>") is None
    assert TikTokClient.extract_from_html(None) is None


def test_demo_profile_is_labelled():
    demo = TikTokClient.demo_profile("someone")
    assert demo["demo"] is True
    assert demo["source"] == "demo"
    assert len(demo["videos"]) == 30


def test_bulk_fetch_result_shape():
    """bulk_fetch returns {username: ProfileResult} even when network fails."""
    import asyncio

    async def run():
        return await bulk_fetch(["definitely_not_a_real_user_xyz"], concurrency=1,
                                want_videos=0)

    results = asyncio.run(run())
    assert "definitely_not_a_real_user_xyz" in results
