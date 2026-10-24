"""
وحدة استخراج الموقع الجغرافي + نوع الهاتف (Geolocation & Device Fingerprinting)
================================================================================

شرح المبدأ ببساطة (Simple explanation of every part):

1) تحليل User-Agent:
   كل طلب HTTP يمرر سلسلة User-Agent تصف المتصفح/التطبيق ونظام التشغيل غالباً.
   تطبيقات تيك توك تضع نمطاً خاصاً مثل:
     "TikTok 32.5.3 rv:325013 (iPhone; iOS 17.2.1; en_US) Cronet"
   → نستخرج منه: إصدار التطبيق + الجهاز + نظام التشغيل + لغة الواجهة.

2) تحليل Headers:
   ترويسات مثل X-Requested-With (اسم حزمة الأندرويد)، Sec-CH-UA-Model
   (Client Hints تكشف موديل الهاتف مباشرة)، Accept-Language (لغة/بلد المستخدم).

3) IP → Geolocation:
   قواعد بيانات Geo تحوّل عنوان IP إلى دولة/مدينة/إحداثيات/مزود خدمة.
   نستخدم سلسلة مزودين مجاناً (ip-api.com ثم ipwho.is) مع geopy
   وreverse_geocoder لتنقية المدينة، وtimezonefinder للمنطقة الزمنية.

4) التعامل مع المعلومات غير المتوفرة (المهم!):
   * IP المستخدم العادي لا يمكن معرفته من اسم مستخدم تيك توك — السيرفرات
     فقط ترى الـ IP. لذلك: الوحدة تعمل على أي IP/Tرويسات "تُمرر لها" —
     مثلاً حركة بوتك نفسه (webhooks)، بيانات تصدير حسابك الخاص، أو أي
     نظام يمرر forwarde-for headers.
   * عند غياب أي حقل: نُرجع None + confidence: "unavailable" + سبب واضح،
     ولا نُخترع قيماً أبداً.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from bot.utils.logger import get_logger

log = get_logger(__name__)

# ── أنماط User-Agent الخاص بتيك توك ───────────────────────────
TIKTOK_UA_RE = re.compile(
    r"TikTok[ /](?P<app_version>[\d.]+).{0,40}?"
    r"(?:\((?P<device>[^;)]+);\s*(?P<os>[^;)]+)[^)]*\))?",
    re.I,
)
IOS_RE = re.compile(r"iOS[\s/]?([\d_.]+)", re.I)
ANDROID_RE = re.compile(r"Android[\s/]?([\d_.]+)", re.I)
IPHONE_RE = re.compile(r"(iPhone\s?\d{1,2}(?:,?\d)*(?:\s?(?:Pro|Max|Plus|mini))*)", re.I)
SAMSUNG_RE = re.compile(r"(SM-[A-Z0-9]{4,10})", re.I)
HUAWEI_RE = re.compile(r"(HUAWEI|Honor)\s*([\w\-]+)", re.I)


@dataclass
class GeoResult:
    """نتيجة تحديد الموقع — أي حقل مفقود يبقى None مع ثقة 'unavailable'."""
    ip: str | None = None
    country: str | None = None
    country_code: str | None = None
    region: str | None = None
    city: str | None = None
    lat: float | None = None
    lon: float | None = None
    timezone: str | None = None
    isp: str | None = None
    org: str | None = None
    asn: str | None = None
    source: str | None = None          # ip-api / ipwho.is / header-hint
    confidence: str = "unavailable"    # high | medium | low | unavailable
    note_ar: str = ""
    note_en: str = ""

    @property
    def gps(self) -> str | None:
        return f"{self.lat:.4f}, {self.lon:.4f}" if self.lat is not None and self.lon is not None else None

    def as_dict(self) -> dict:
        return {
            "ip": self.ip, "country": self.country, "country_code": self.country_code,
            "region": self.region, "city": self.city, "lat": self.lat, "lon": self.lon,
            "gps": self.gps, "timezone": self.timezone, "isp": self.isp,
            "org": self.org, "asn": self.asn, "source": self.source,
            "confidence": self.confidence, "note_ar": self.note_ar, "note_en": self.note_en,
        }


@dataclass
class DeviceInfo:
    """معلومات الجهاز المستخرجة من الترويسات/UA — الحقول المفقودة None."""
    brand: str | None = None            # Apple / Samsung / Huawei / Xiaomi ...
    model: str | None = None            # iPhone 15 Pro Max / SM-S928B ...
    os_name: str | None = None          # iOS / Android
    os_version: str | None = None       # 17.2.1 / 14
    browser: str | None = None          # Chrome / Safari / TikTok-App
    browser_version: str | None = None
    app_version: str | None = None      # 32.5.3 (تطبيق تيك توك)
    app_package: str | None = None      # com.zhiliaoapp.musically
    device_id_masked: str | None = None # مُقنّع: 6f3****…**a9 (لا يُخزن كاملاً أبداً)
    network_type: str | None = None     # wifi / 4G / 5G (إن أعلنها المصدر)
    interface_language: str | None = None  # من Accept-Language
    source: str | None = None           # user-agent / headers / payload
    confidence: str = "unavailable"
    raw: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "brand": self.brand, "model": self.model, "os": (
                f"{self.os_name} {self.os_version}".strip() if self.os_name else None),
            "browser": self.browser, "browser_version": self.browser_version,
            "app_version": self.app_version, "app_package": self.app_package,
            "device_id_masked": self.device_id_masked, "network_type": self.network_type,
            "interface_language": self.interface_language,
            "source": self.source, "confidence": self.confidence,
        }


PRIVATE_IP_RE = re.compile(
    r"^(127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|::1|fc00:|fe80:)", re.I
)


# ══════════════════════════════════════════════════════════════
# 1) User-Agent analyzer
# ══════════════════════════════════════════════════════════════
class UserAgentAnalyzer:
    """
    يستخرج هوية الجهاز من سلسلة User-Agent.
    المبدأ: كل نظام/تطبيق يترك بصمة نصية قياسية في الترويسة يمكن تحليلها
    بالتعابير النمطية + مكتبة user-agents للتفاصيل الدقيقة.
    """

    def parse(self, ua: str | None) -> DeviceInfo:
        info = DeviceInfo(source="user-agent", raw={"ua": ua or ""})
        if not ua:
            info.note = "no user-agent"          # type: ignore[attr-defined]
            return info

        ua_lower = ua.lower()

        # brand & model (أولوية للتطابقات الدقيقة)
        m = IPHONE_RE.search(ua)
        if m:
            info.brand, info.model = "Apple", m.group(1).strip()
        elif (m := SAMSUNG_RE.search(ua)):
            info.brand, info.model = "Samsung", m.group(1).upper()
        elif (m := HUAWEI_RE.search(ua)):
            info.brand = "Huawei" if m.group(1).lower() == "huawei" else "Honor"
            info.model = m.group(2)
        elif "iphone" in ua_lower:
            info.brand, info.model = "Apple", "iPhone"
        elif "ipad" in ua_lower:
            info.brand, info.model = "Apple", "iPad"
        elif "android" in ua_lower:
            info.brand = "Android device"       # الموديل غالباً في Client Hints

        # OS
        if (m := IOS_RE.search(ua)):
            info.os_name, info.os_version = "iOS", m.group(1).replace("_", ".")
        elif (m := ANDROID_RE.search(ua)):
            info.os_name, info.os_version = "Android", m.group(1)
        elif "windows" in ua_lower:
            info.os_name = "Windows"
        elif "mac os" in ua_lower or "macintosh" in ua_lower:
            info.os_name = "macOS"

        # Browser / App
        m_tiktok = TIKTOK_UA_RE.search(ua)
        if m_tiktok:
            info.browser = "TikTok App"
            info.app_version = m_tiktok.group("app_version")
            info.confidence = "high"
        elif "edg/" in ua_lower:
            info.browser = "Edge"
            info.browser_version = ua.split("Edg/")[-1].split(" ")[0]
        elif "chrome/" in ua_lower and "edg" not in ua_lower:
            info.browser = "Chrome"
            info.browser_version = ua.split("Chrome/")[-1].split(" ")[0]
        elif "safari" in ua_lower and "version/" in ua_lower:
            info.browser = "Safari"
            info.browser_version = ua.split("Version/")[-1].split(" ")[0]
        elif "firefox" in ua_lower:
            info.browser = "Firefox"
            info.browser_version = ua.split("Firefox/")[-1].split(" ")[0]

        if info.brand or info.os_name:
            info.confidence = "medium" if info.confidence == "unavailable" else info.confidence
        return info


# ══════════════════════════════════════════════════════════════
# 2) HTTP Headers analyzer
# ══════════════════════════════════════════════════════════════
class HeaderAnalyzer:
    """
    يستخرج أدلة الجهاز واللغة من ترويسات HTTP القياسية.
    المبدأ: Client Hints (sec-ch-ua-*) صممت لتقول للمواقع "من أنا" بإذن
    المستخدم — وهي أوضح مصدر لموديل الهاتف عند توفرها.
    """

    def parse(self, headers: dict) -> DeviceInfo:
        info = DeviceInfo(source="headers", raw=dict(headers))
        get = lambda k: headers.get(k) or headers.get(k.lower()) or headers.get(k.upper())  # noqa: E731

        model = get("sec-ch-ua-model")
        platform = get("sec-ch-ua-platform")
        pkg = get("x-requested-with")
        lang = get("accept-language")

        if model:
            info.model = model
            info.brand = _brand_from_model(model)
            info.confidence = "high"
        if pkg and "musically" in pkg.lower():
            info.app_package = pkg
            info.browser = "TikTok App"
            info.confidence = "high"
        if platform:
            info.os_name = platform.title()
        if lang:
            info.interface_language = lang.split(",")[0].strip()

        # دمج مع UA لاستكمال الناقص
        ua_info = UserAgentAnalyzer().parse(get("user-agent"))
        merged = DeviceInfo(source="user-agent+headers", raw=info.raw)
        for attr in ("brand", "model", "os_name", "os_version", "browser",
                     "browser_version", "app_version", "app_package",
                     "interface_language", "network_type"):
            val = getattr(info, attr) or getattr(ua_info, attr)
            setattr(merged, attr, val)
        merged.confidence = max_conf(info.confidence, ua_info.confidence)
        return merged


def _brand_from_model(model: str) -> str | None:
    m = model.lower()
    if m.startswith(("sm-", "gt-")):
        return "Samsung"
    if "iphone" in m:
        return "Apple"
    if "huawei" in m or m.startswith("els-") or m.startswith("voq-"):
        return "Huawei"
    if "pixel" in m:
        return "Google"
    if m.startswith(("redmi", "mi ", "m2", "2212")):
        return "Xiaomi"
    return None


def max_conf(*confs: str) -> str:
    order = {"unavailable": 0, "low": 1, "medium": 2, "high": 3}
    return max(confs, key=lambda c: order.get(c, 0)) if confs else "unavailable"


# ══════════════════════════════════════════════════════════════
# 3) IP → Geolocation (provider chain + refinement)
# ══════════════════════════════════════════════════════════════
class IPGeolocation:
    """
    يحوّل IP إلى موقع: دولة/مدينة/إحداثيات/مزود/منطقة زمنية.
    المبدأ: قواعد بيانات Geo تربط نطاقات IP بالمواقع المسجلة لمزودي الخدمة.
    نستخدم سلسلة احتياطية من مزودين مجانيين + تنقية عبر reverse_geocoder.
    """

    PROVIDERS = ("ip-api", "ipwho.is")

    async def locate(self, ip: str | None) -> GeoResult:
        if not ip:
            return GeoResult(note_ar="لا يوجد IP لتحليله", note_en="no IP to analyse")
        if PRIVATE_IP_RE.match(ip):
            return GeoResult(ip=ip, confidence="unavailable",
                             note_ar="عنوان داخلي/خاص لا يُحدد جغرافياً",
                             note_en="private/local IP — not geolocatable")

        for provider in self.PROVIDERS:
            result = await self._query_provider(provider, ip)
            if result and result.country:
                self._refine(result)
                return result
        return GeoResult(ip=ip, note_ar="فشل كل المزودين", note_en="all providers failed")

    async def _query_provider(self, provider: str, ip: str) -> GeoResult | None:
        try:
            import aiohttp

            timeout = aiohttp.ClientTimeout(total=8)
            async with aiohttp.ClientSession(timeout=timeout) as http:
                if provider == "ip-api":
                    url = (f"http://ip-api.com/json/{ip}"
                           "?fields=status,country,countryCode,regionName,city,lat,lon,timezone,isp,org,as,query")
                    async with http.get(url) as resp:
                        data = await resp.json(content_type=None)
                    if data.get("status") != "success":
                        return None
                    return GeoResult(
                        ip=ip, country=data.get("country"), country_code=data.get("countryCode"),
                        region=data.get("regionName"), city=data.get("city"),
                        lat=data.get("lat"), lon=data.get("lon"), timezone=data.get("timezone"),
                        isp=data.get("isp"), org=data.get("org"), asn=data.get("as"),
                        source="ip-api.com", confidence="high",
                    )
                if provider == "ipwho.is":
                    url = f"https://ipwho.is/{ip}"
                    async with http.get(url) as resp:
                        data = await resp.json(content_type=None)
                    if not data.get("success"):
                        return None
                    return GeoResult(
                        ip=ip, country=data.get("country"), country_code=data.get("country_code"),
                        region=(data.get("region") or None), city=data.get("city"),
                        lat=data.get("latitude"), lon=data.get("longitude"),
                        timezone=(data.get("timezone") or {}).get("id"),
                        isp=data.get("connection", {}).get("isp"),
                        org=data.get("connection", {}).get("org"),
                        asn=str(data.get("connection", {}).get("asn") or "") or None,
                        source="ipwho.is", confidence="medium",
                    )
        except Exception as exc:  # noqa: BLE001
            log.warning("geo provider %s failed: %s", provider, exc)
            return None
        return None

    @staticmethod
    def _refine(result: GeoResult) -> None:
        """تنقية المدينة من الإحداثيات + استنتاج المنطقة الزمنية إن غابت."""
        if result.lat is not None and result.lon is not None:
            try:
                import reverse_geocoder  # heavy import — lazy

                res = reverse_geocoder.search((result.lat, result.lon))
                if res and not result.city:
                    result.city = res[0].get("name")
                    if not result.country_code:
                        result.country_code = res[0].get("cc")
            except Exception:  # noqa: BLE001
                pass
        if not result.timezone and result.lat is not None:
            try:
                from timezonefinder import TimezoneFinder

                result.timezone = TimezoneFinder().timezone_at(lat=result.lat, lng=result.lon)
            except Exception:  # noqa: BLE001
                pass


# ══════════════════════════════════════════════════════════════
# 4) Device-info extraction from TikTok payloads
# ══════════════════════════════════════════════════════════════
class DeviceInfoExtractor:
    """
    ملاحظة صدق مهمة: معرّف الجهاز (device_id) وإعدادات التطبيق الخاصة
    بـ"صاحب الحساب المستهدف" لا يمكن الحصول عليها من أي مصدر عام —
    تُستخرج فقط من بيانات جهازك أنت (تصدير بيانات تيك توك، أو ترويسات
    طلبات تطبيقك). الوحدة هنا تعالج أي payload تمرره لها بصدق تام.
    """

    @staticmethod
    def mask_device_id(did: str | None) -> str | None:
        """تقنيع المعرف: نحفظ أول 3 وأخر 2 فقط — لا يُخزن كاملاً أبداً."""
        if not did or len(did) < 6:
            return None
        return f"{did[:3]}****{did[-2:]}"

    def from_payload(self, payload: dict) -> DeviceInfo:
        info = DeviceInfo(source="payload", raw={k: payload.get(k) for k in
                                                 ("device_id", "device_model", "os_type",
                                                  "os_version", "app_version", "device_platform")})
        info.brand = payload.get("device_brand") or _brand_from_model(payload.get("device_model") or "")
        info.model = payload.get("device_model")
        info.os_name = payload.get("os_type") or payload.get("device_platform")
        info.os_version = str(payload.get("os_version") or "") or None
        info.app_version = str(payload.get("app_version") or "") or None
        info.device_id_masked = self.mask_device_id(payload.get("device_id"))
        info.confidence = "high" if (info.model or info.device_id_masked) else "unavailable"
        return info


# ══════════════════════════════════════════════════════════════
# Facade — واجهة واحدة تجمع كل الأساليب
# ══════════════════════════════════════════════════════════════
class GeolocationFacade:
    """نقطة دخول واحدة: مرّر IP و/أو ترويسات و/أو payload واحصل على النتيجة."""

    def __init__(self):
        self._geo = IPGeolocation()
        self._ua = UserAgentAnalyzer()
        self._headers = HeaderAnalyzer()
        self._device = DeviceInfoExtractor()

    async def full_analysis(self, *, ip: str | None = None, headers: dict | None = None,
                            payload: dict | None = None) -> dict:
        geo = await self._geo.locate(ip)
        if headers:
            device = self._headers.parse(headers)
        elif payload:
            device = self._device.from_payload(payload)
        else:
            device = DeviceInfo()
        return {
            "geo": geo.as_dict(),
            "device": device.as_dict(),
            "honesty_note": {
                "ar": "الموقع/الجهاز يُستخرج فقط من بيانات تُمرر للوحدة (IP، ترويسات، payload). "
                      "اسم مستخدم تيك توك لا يكشف IP صاحبه — وهذا بحد ذاته حماية للخصوصية.",
                "en": "Location/device are extracted only from data you pass in (IP, headers, "
                      "payload). A TikTok username never reveals its owner's IP — by design.",
            },
        }


__all__ = ["GeoResult", "DeviceInfo", "UserAgentAnalyzer", "HeaderAnalyzer",
           "IPGeolocation", "DeviceInfoExtractor", "GeolocationFacade"]
