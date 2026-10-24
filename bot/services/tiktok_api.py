"""
TikTok data collector — reads **public** profile data from the TikTok web page.

Method (why it works):
---------------------
When a browser opens https://www.tiktok.com/@<user>, TikTok embeds a big JSON
blob in `<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">`.  That blob contains
the public user object (user + stats) and the first page of public videos.
We simply fetch the page with browser-like headers and parse that JSON.
Nothing private is accessed; everything returned is what any visitor sees.

Failure handling:
-----------------
* TikTok may return a challenge page (no JSON)  → we retry, then fall back to
  clearly-labelled DEMO data if `demo_fallback` is enabled.
* Fields that no public endpoint exposes (creation IP, GPS, device id, …)
  are listed in FIELD_AVAILABILITY so the UI can mark them honestly.
"""
from __future__ import annotations

import asyncio
import json
import random
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from bot.utils.logger import get_logger
from bot.utils.validators import extract_emails, extract_phones
from config.settings import get_settings

log = get_logger(__name__)

UNIVERSAL_RE = re.compile(
    r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', re.S
)
SIGI_RE = re.compile(r'<script id="sigi-persisted-data"[^>]*>(.*?)</script>', re.S)

DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class DataAvailability(str, Enum):
    AVAILABLE = "AVAILABLE"      # public data any visitor can see
    DERIVED = "DERIVED"          # computed by us from public data (estimates)
    UNAVAILABLE = "UNAVAILABLE"  # private/server-side — no honest way to obtain


@dataclass
class FieldMeta:
    availability: DataAvailability
    reason_ar: str
    reason_en: str


FIELD_AVAILABILITY: dict[str, FieldMeta] = {
    "creation_ip": FieldMeta(DataAvailability.UNAVAILABLE,
                             "IP الإنشاء بيانات سيرفرية لا تُشارك مع أي زائر",
                             "Creation IP is server-side data never shown to visitors"),
    "gps": FieldMeta(DataAvailability.UNAVAILABLE,
                     "إحداثيات الإنشاء غير منشورة إطلاقاً",
                     "Creation coordinates are never published"),
    "registered_email": FieldMeta(DataAvailability.UNAVAILABLE,
                                  "الإيميل المسجل خاص بصاحب الحساب",
                                  "The registered email is private to the owner"),
    "registered_phone": FieldMeta(DataAvailability.UNAVAILABLE,
                                  "الهاتف المسجل خاص بصاحب الحساب",
                                  "The registered phone is private to the owner"),
    "device_id": FieldMeta(DataAvailability.UNAVAILABLE,
                           "Device ID يُستخرج فقط من جهاز صاحب الحساب نفسه",
                           "Device ID is only extractable from the owner's own device"),
    "session_id": FieldMeta(DataAvailability.UNAVAILABLE,
                            "Session ID خاص بجلسة الدخول",
                            "Session ID belongs to a private login session"),
    "creation_time": FieldMeta(DataAvailability.UNAVAILABLE,
                               "تاريخ إنشاء الحساب غير معروض في الملف العام",
                               "Account creation date is not shown on the public profile"),
    "verified_date": FieldMeta(DataAvailability.UNAVAILABLE,
                               "تاريخ التوثيق غير معلن",
                               "Verification date is not disclosed"),
    "username_history": FieldMeta(DataAvailability.UNAVAILABLE,
                                  "تيك توك لا ينشر سجل تغيير الأسماء",
                                  "TikTok does not publish username change history"),
    "password_strength": FieldMeta(DataAvailability.UNAVAILABLE,
                                   "كلمات المرور لا تُخزن مقروءة لدى أي طرف",
                                   "Passwords are never stored readable"),
    "breach_history": FieldMeta(DataAvailability.UNAVAILABLE,
                                "فحص تسريبات الحسابات يتطلب مفتاح HIBP مدفوعاً وخصوصية",
                                "Account breach lookup needs paid HIBP key + privacy care"),
    "followers_country": FieldMeta(DataAvailability.DERIVED,
                                   "التوزيع الجغرافي للجمهور متاح فقط لصاحب الحساب",
                                   "Audience geo is only visible to the account owner"),
    "followers_age": FieldMeta(DataAvailability.DERIVED,
                               "أعمار الجمهور متاحة فقط لصاحب الحساب",
                               "Audience age is only visible to the owner"),
    "followers_gender": FieldMeta(DataAvailability.DERIVED,
                                  "نسب الجنس متاحة فقط لصاحب الحساب",
                                  "Audience gender is only visible to the owner"),
    "fan_vs_nonfan_views": FieldMeta(DataAvailability.DERIVED,
                                     "نسبة مشاهدة المتابعين/غير المتابعين خاصة بالتحليلات",
                                     "Fan vs non-fan views is private analytics"),
    "region": FieldMeta(DataAvailability.AVAILABLE,
                        "رمز الدولة العام في بيانات الملف",
                        "Public region code in the profile payload"),
    "bio_contacts": FieldMeta(DataAvailability.AVAILABLE,
                              "ما يكتبه صاحب الحساب بنفسه في نبذته عام",
                              "What the owner writes in their own bio is public"),
}


@dataclass
class ProfileResult:
    username: str
    ok: bool
    demo: bool = False
    data: dict = field(default_factory=dict)
    error: str | None = None


class TikTokClient:
    """Async public-data collector with retries, proxy support and caching."""

    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        self._session = None

    # ── low-level HTTP ───────────────────────────────────────
    async def _get_session(self):
        if self._session is None or self._session.closed:
            import aiohttp

            headers = {
                "User-Agent": DESKTOP_UA,
                "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
            }
            cookie = self.settings.tiktok_sessionid
            if cookie:
                headers["Cookie"] = f"sessionid={cookie}"
            self._session = aiohttp.ClientSession(
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=self.settings.scraping_timeout),
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def _get_text(self, url: str) -> str | None:
        from tenacity import retry, stop_after_attempt, wait_exponential

        @retry(stop=stop_after_attempt(self.settings.scraping_retries),
               wait=wait_exponential(multiplier=1, min=1, max=6), reraise=True)
        async def _do():
            session = await self._get_session()
            proxy = self.settings.scraping_proxy or None
            async with session.get(url, proxy=proxy) as resp:
                if resp.status != 200:
                    log.warning("GET %s → HTTP %s", url[:90], resp.status)
                    return None
                return await resp.text()

        try:
            return await _do()
        except Exception as exc:  # noqa: BLE001
            log.warning("fetch failed %s: %s", url[:90], exc)
            return None

    # ── public API ───────────────────────────────────────────
    async def fetch_profile(self, username: str, want_videos: int | None = None) -> ProfileResult:
        """Fetch a public profile; falls back to labelled demo data when blocked."""
        want_videos = want_videos if want_videos is not None else min(30, self.settings.videos_deep_count)
        html = await self._get_text(f"https://www.tiktok.com/@{username}")
        parsed = self.extract_from_html(html) if html else None
        if parsed is None:
            if self.settings.demo_fallback:
                return ProfileResult(username=username, ok=True, demo=True,
                                     data=self.demo_profile(username))
            return ProfileResult(username=username, ok=False, error="blocked_or_not_found")

        profile = parsed["profile"]
        videos = parsed["videos"][:want_videos]
        sec_uid = profile.get("sec_uid") or ""
        if 0 < len(videos) < want_videos and sec_uid:
            extra = await self._fetch_more_videos(sec_uid, cursor=len(videos),
                                                  count=want_videos - len(videos))
            seen = {v["id"] for v in videos}
            videos += [v for v in extra if v["id"] not in seen]

        profile["videos"] = videos
        profile["demo"] = False
        profile["source"] = "tiktok-web"
        profile["fetched_at"] = datetime.now(timezone.utc).isoformat()
        return ProfileResult(username=username, ok=True, data=profile)

    async def _fetch_more_videos(self, sec_uid: str, cursor: int, count: int) -> list[dict]:
        """Best-effort pagination of the public post list (may be signature-protected)."""
        url = (
            "https://www.tiktok.com/api/post/item_list/"
            f"?aid=1988&count={count}&cursor={cursor}&secUid={sec_uid}"
        )
        raw = await self._get_text(url)
        if not raw:
            return []
        try:
            payload = json.loads(raw)
            return [self._normalize_video(it) for it in payload.get("itemList", []) if it]
        except (json.JSONDecodeError, AttributeError):
            return []

    # ── parsing (pure functions → unit-testable) ─────────────
    @staticmethod
    def extract_from_html(html: str | None) -> dict | None:
        if not html:
            return None
        match = UNIVERSAL_RE.search(html) or SIGI_RE.search(html)
        if not match:
            return None
        try:
            blob = json.loads(match.group(1))
        except json.JSONDecodeError:
            return None
        scope = blob.get("__DEFAULT_SCOPE__", {})
        detail = (scope.get("webapp.user-detail") or {})
        user_info = detail.get("userInfo") or {}
        user = user_info.get("user") or {}
        stats = user_info.get("stats") or {}
        if not user:
            return None

        profile = {
            "username": user.get("uniqueId"),
            "id": user.get("id"),
            "sec_uid": user.get("secUid"),
            "nickname": user.get("nickname"),
            "bio": user.get("signature") or "",
            "avatar": user.get("avatarLarger") or user.get("avatarMedium") or "",
            "cover": user.get("videoCover") or "",
            "verified": bool(user.get("verified")),
            "private": bool(user.get("privateAccount")),
            "bio_link": (user.get("bioLink") or {}).get("link"),
            "region": user.get("region"),
            "language": user.get("language"),
            "followers": int(stats.get("followerCount") or 0),
            "following": int(stats.get("followingCount") or 0),
            "likes": int(stats.get("heartCount") or 0),
            "videos_count": int(stats.get("videoCount") or 0),
        }
        # public contacts the owner voluntarily wrote in their own bio
        profile["emails"] = extract_emails(profile.get("bio"))
        profile["phones"] = extract_phones(profile.get("bio"))
        profile["socials"] = TikTokClient._extract_socials(
            profile.get("bio") or "", profile.get("bio_link"))
        videos = [TikTokClient._normalize_video(it)
                  for it in (detail.get("itemList") or []) if it]
        return {"profile": profile, "videos": videos}

    @staticmethod
    def _normalize_video(item: dict) -> dict:
        stats = item.get("stats") or item.get("statsV2") or {}
        music = item.get("music") or {}
        hashtags = [c.get("hashtagName") for c in (item.get("textExtra") or [])
                    if isinstance(c, dict) and c.get("hashtagName")]
        video_obj = item.get("video") or {}
        return {
            "id": item.get("id"),
            "create_time": item.get("createTime"),
            "duration": item.get("video", {}).get("duration") if isinstance(item.get("video"), dict) else None,
            "views": int(stats.get("playCount") or 0),
            "likes": int(stats.get("diggCount") or 0),
            "comments": int(stats.get("commentCount") or 0),
            "shares": int(stats.get("shareCount") or 0),
            "bookmarks": int(stats.get("collectCount") or 0),
            "desc": item.get("desc") or "",
            "hashtags": hashtags,
            "music_title": music.get("title"),
            "music_author": music.get("authorName"),
            "location": (item.get("locationCreated") or None),
            "cover": video_obj.get("cover") if isinstance(video_obj, dict) else None,
        }

    @staticmethod
    def _extract_socials(bio: str, bio_link: str | None) -> dict[str, str]:
        """Detect linked social accounts the owner published themselves."""
        socials: dict[str, str] = {}
        patterns = {
            "instagram": re.compile(r"@?\s*(?:ig|instagram)[:\s]*@?([A-Za-z0-9_.]{2,30})", re.I),
            "twitter": re.compile(r"(?:twitter|x)\s*[:@]\s*([A-Za-z0-9_]{2,20})", re.I),
            "youtube": re.compile(r"youtube\.com/(?:c/|channel/|@)([A-Za-z0-9_\-]{2,40})", re.I),
            "snapchat": re.compile(r"snap(?:chat)?\s*[:]\s*([A-Za-z0-9_.]{2,30})", re.I),
        }
        for net, rx in patterns.items():
            m = rx.search(bio or "")
            if m:
                socials[net] = m.group(1)
        if bio_link and "instagram" in (bio_link or ""):
            socials.setdefault("instagram", bio_link.split("instagram.com/")[-1].strip("/"))
        return socials

    @staticmethod
    def demo_profile(username: str) -> dict:
        """Synthetic, clearly-labelled sample used ONLY when TikTok is unreachable."""
        rnd = random.Random(username)  # deterministic per username
        followers = rnd.randint(1_000, 900_000)
        base_views = int(followers * rnd.uniform(0.15, 0.8))
        videos = []
        now_ts = int(datetime.now(timezone.utc).timestamp())
        for i in range(30):
            videos.append({
                "id": f"demo{i}_{username}",
                "create_time": now_ts - i * 86_400 // 2,
                "duration": rnd.choice([15, 21, 34, 47, 60]),
                "views": int(base_views * rnd.uniform(0.4, 1.9)),
                "likes": int(base_views * rnd.uniform(0.04, 0.16)),
                "comments": int(base_views * rnd.uniform(0.003, 0.02)),
                "shares": int(base_views * rnd.uniform(0.002, 0.015)),
                "bookmarks": int(base_views * rnd.uniform(0.001, 0.01)),
                "desc": f"demo video {i + 1} #fyp #demo",
                "hashtags": ["fyp", "demo", f"tag{i % 7}"],
                "music_title": "Demo Track", "music_author": "Demo Artist",
                "location": None, "cover": None,
            })
        return {
            "username": username, "id": "0000000000000000000", "sec_uid": "",
            "nickname": f"Demo {username}", "bio": "DEMO DATA — TikTok unreachable",
            "avatar": "", "cover": "", "verified": rnd.random() < 0.2,
            "private": False, "bio_link": None, "region": "SA", "language": "ar",
            "followers": followers, "following": rnd.randint(50, 800),
            "likes": followers * rnd.randint(8, 40), "videos_count": rnd.randint(30, 600),
            "videos": videos, "emails": [], "phones": [], "socials": {},
            "demo": True, "source": "demo", "fetched_at": datetime.now(timezone.utc).isoformat(),
        }


async def bulk_fetch(usernames: list[str], concurrency: int = 5,
                     want_videos: int = 0) -> dict[str, ProfileResult]:
    """Parallel scans with a semaphore so we stay polite."""
    client = TikTokClient()
    sem = asyncio.Semaphore(concurrency)

    async def one(name: str) -> tuple[str, ProfileResult]:
        async with sem:
            try:
                return name, await client.fetch_profile(name, want_videos=want_videos)
            except Exception as exc:  # noqa: BLE001
                log.warning("bulk fetch %s failed: %s", name, exc)
                return name, ProfileResult(username=name, ok=False, error=str(exc))

    try:
        results = await asyncio.gather(*(one(u) for u in usernames))
        return dict(results)
    finally:
        await client.close()


__all__ = ["TikTokClient", "ProfileResult", "DataAvailability", "FIELD_AVAILABILITY", "bulk_fetch"]
