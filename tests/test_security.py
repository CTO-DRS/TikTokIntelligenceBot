"""
Security unit tests — AES roundtrip, role order, rate limiter (memory mode),
password heuristics, injection detection, geo header parsing.
"""
from __future__ import annotations

import asyncio
import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.services.geolocation import UserAgentAnalyzer, HeaderAnalyzer, DeviceInfoExtractor  # noqa: E402
from bot.services.security import (  # noqa: E402
    AES256Cipher, PasswordAnalyzer, ProfileSecurityScorer, RateLimiter, Roles,
)
from bot.utils.validators import detect_injection  # noqa: E402


def _key() -> str:
    return base64.b64encode(bytes(range(32))).decode()


def test_aes_roundtrip():
    cipher = AES256Cipher(_key())
    token = cipher.encrypt("سري جداً secret-123 ✅")
    assert token != "سري جداً secret-123 ✅"
    assert cipher.decrypt(token) == "سري جداً secret-123 ✅"


def test_aes_rejects_short_key():
    short = base64.b64encode(b"0123").decode()
    try:
        AES256Cipher(short)
        assert False, "should have raised"
    except ValueError:
        pass


def test_roles_order():
    assert Roles.BANNED < Roles.USER < Roles.VIP < Roles.ADMIN < Roles.SUPER_ADMIN


def test_rate_limiter_memory_mode():
    limiter = RateLimiter("")  # no redis → memory fallback
    async def run():
        results = []
        for _ in range(5):
            results.append(await limiter.allow("k", 3, 60))
        return results
    results = asyncio.run(run())
    assert results == [True, True, True, False, False]


def test_password_strength_signal():
    weak = PasswordAnalyzer.strength("123456")
    strong = PasswordAnalyzer.strength("Tr0ub4dor&3-Correct-Horse!")
    assert weak["score"] <= 5
    assert strong["score"] > weak["score"]


def test_injection_detection():
    assert detect_injection("'; DROP TABLE users; --")
    assert detect_injection("<script>alert(1)</script>")
    assert detect_injection("../../etc/passwd")
    assert not detect_injection("ordinary username_1")


def test_security_scorer_public_signals():
    safe = ProfileSecurityScorer.score({"private": True, "verified": True,
                                        "emails": [], "phones": [],
                                        "bio_link": None, "username": "complex_user1"})
    leaky = ProfileSecurityScorer.score({"private": False, "verified": False,
                                         "emails": ["a@b.co"], "phones": ["0501234567"],
                                         "bio_link": "https://x.com", "username": "user1"})
    assert safe["score"] > leaky["score"]


def test_user_agent_iphone_tiktok():
    ua = ("TikTok 32.5.3 rv:325013 (iPhone; iOS 17.2.1; en_US) Cronet")
    info = UserAgentAnalyzer().parse(ua)
    d = info.as_dict()
    assert d["brand"] == "Apple"
    assert d["os"] == "iOS 17.2.1"
    assert d["app_version"] == "32.5.3"
    assert d["confidence"] in {"medium", "high"}


def test_user_agent_android_samsung():
    ua = ("Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36")
    d = UserAgentAnalyzer().parse(ua).as_dict()
    assert d["brand"] == "Samsung"
    assert d["os"].startswith("Android 14")
    assert d["browser"] == "Chrome"


def test_header_analyzer_client_hints():
    headers = {
        "sec-ch-ua-model": "Pixel 8 Pro",
        "sec-ch-ua-platform": "android",
        "accept-language": "ar-SA,ar;q=0.9,en;q=0.8",
        "user-agent": "Mozilla/5.0 (Linux; Android 14) Chrome/124 Mobile",
    }
    d = HeaderAnalyzer().parse(headers).as_dict()
    assert d["model"] == "Pixel 8 Pro"
    assert d["interface_language"].startswith("ar-SA".split(",")[0][:2]) or d["interface_language"]


def test_device_id_masking():
    masked = DeviceInfoExtractor.mask_device_id("6782937465018274059")
    assert masked.startswith("678") and masked.endswith("59")
    assert "6782937465018274059" not in (masked or "")
    assert DeviceInfoExtractor.mask_device_id("123") is None
