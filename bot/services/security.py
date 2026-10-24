"""
Security services — encryption, roles, rate limiting, 2FA, breach checking,
profile security scoring.  All primitives are honest and standard-based.
"""
from __future__ import annotations

import base64
import hashlib
import os
import re
import time
from collections import deque
from pathlib import Path

from bot.utils.logger import get_logger
from config.settings import BASE_DIR, get_settings

log = get_logger(__name__)

# ══════════════════════════════════════════════════════════════
# AES-256-GCM symmetric encryption
# ══════════════════════════════════════════════════════════════
class AES256Cipher:
    """
    AES-256-GCM authenticated encryption.

    * key: 32 random bytes (AES-256), loaded from settings or auto-generated
      and persisted with 0600 permissions at data/secret.key.
    * output layout: base64(nonce[12] || ciphertext+tag)
    """

    def __init__(self, key_b64: str = ""):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        key = self._resolve_key(key_b64)
        self._aesgcm = AESGCM(key)

    @staticmethod
    def _resolve_key(key_b64: str) -> bytes:
        if key_b64:
            key = base64.b64decode(key_b64)
            if len(key) != 32:
                raise ValueError("ENCRYPTION_KEY must decode to exactly 32 bytes")
            return key
        key_file = BASE_DIR / "data" / "secret.key"
        if key_file.exists():
            return base64.b64decode(key_file.read_text().strip())
        key = os.urandom(32)
        key_file.parent.mkdir(parents=True, exist_ok=True)
        key_file.write_text(base64.b64encode(key).decode())
        try:
            key_file.chmod(0o600)
        except OSError:
            pass
        log.info("generated new AES-256 key at %s", key_file)
        return key

    def encrypt(self, plaintext: str) -> str:
        nonce = os.urandom(12)
        ct = self._aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
        return base64.b64encode(nonce + ct).decode("ascii")

    def decrypt(self, token: str) -> str:
        raw = base64.b64decode(token.encode("ascii"))
        nonce, ct = raw[:12], raw[12:]
        return self._aesgcm.decrypt(nonce, ct, None).decode("utf-8")


# ══════════════════════════════════════════════════════════════
# Roles (5 levels)
# ══════════════════════════════════════════════════════════════
class Roles:
    BANNED = 0
    USER = 1
    VIP = 2
    ADMIN = 3
    SUPER_ADMIN = 4

    NAMES = {0: "BANNED", 1: "USER", 2: "VIP", 3: "ADMIN", 4: "SUPER_ADMIN"}


class RoleUtils:
    @staticmethod
    def role_of(telegram_id: int) -> int:
        settings = get_settings()
        if telegram_id in settings.admin_ids:
            return Roles.SUPER_ADMIN
        # DB lookup is done by handlers when needed; default is USER
        return _DB_ROLES.get(telegram_id, Roles.USER)

    @staticmethod
    def is_banned(telegram_id: int) -> bool:
        return RoleUtils.role_of(telegram_id) == Roles.BANNED


# populated by handlers after DB fetch (keeps role checks O(1))
_DB_ROLES: dict[int, int] = {
    Roles.BANNED: 0,
    Roles.USER: 1,
    Roles.VIP: 2,
    Roles.ADMIN: 3,
    Roles.SUPER_ADMIN: 4,
}


_ROLE_IDS = {"BANNED": Roles.BANNED, "USER": Roles.USER, "VIP": Roles.VIP,
             "ADMIN": Roles.ADMIN, "SUPER_ADMIN": Roles.SUPER_ADMIN}


def sync_role_cache(telegram_id: int, role_name: str) -> None:
    _DB_ROLES[telegram_id] = _ROLE_IDS.get((role_name or "").upper(), Roles.USER)


# ══════════════════════════════════════════════════════════════
# Multi-tier rate limiter (Redis sliding window, memory fallback)
# ══════════════════════════════════════════════════════════════
class RateLimiter:
    def __init__(self, redis_url: str = ""):
        self._redis = None
        self._memory: dict[str, deque[float]] = {}
        if redis_url:
            try:
                import redis.asyncio as aioredis

                self._redis = aioredis.from_url(redis_url, decode_responses=True,
                                                socket_connect_timeout=2)
            except Exception:  # noqa: BLE001
                self._redis = None
                log.warning("redis unavailable — rate limiter uses in-memory fallback")

    async def allow(self, key: str, limit: int, window_seconds: int) -> bool:
        now = time.time()
        if self._redis is not None:
            try:
                k = f"rl:{key}"
                import redis.asyncio as aioredis

                async with self._redis.pipeline(transaction=True) as pipe:
                    pipe.zremrangebyscore(k, 0, now - window_seconds)
                    pipe.zcard(k)
                    pipe.zadd(k, {str(now): now})
                    pipe.expire(k, window_seconds)
                    res = await pipe.execute()
                return int(res[1]) < limit
            except Exception:  # noqa: BLE001
                self._redis = None  # degrade permanently for this process
        dq = self._memory.setdefault(key, deque())
        cutoff = now - window_seconds
        while dq and dq[0] < cutoff:
            dq.popleft()
        if len(dq) >= limit:
            return False
        dq.append(now)
        return True


# ══════════════════════════════════════════════════════════════
# 2FA (TOTP) for admins
# ══════════════════════════════════════════════════════════════
class TwoFactor:
    @staticmethod
    def new_secret() -> str:
        import pyotp

        return pyotp.random_base32()

    @staticmethod
    def provisioning_uri(secret: str, account: str) -> str:
        import pyotp

        return pyotp.totp.TOTP(secret).provisioning_uri(
            name=account, issuer_name="TikTok Intelligence Bot"
        )

    @staticmethod
    def verify(secret: str, code: str) -> bool:
        import pyotp

        return pyotp.totp.TOTP(secret).verify(code, valid_window=1)


# ══════════════════════════════════════════════════════════════
# Password strength (offline heuristics) + breach lookup
# ══════════════════════════════════════════════════════════════
class PasswordAnalyzer:
    """Estimate password strength 0-100 + crack-time (never sends the password anywhere
    except the k-anonymity 5-char SHA-1 prefix — the standard privacy-safe protocol)."""

    COMMON = {"123456", "password", "123456789", "qwerty", "111111", "12345678",
              "abc123", "password1", "iloveyou", "000000", "admin", "tiktok123"}

    @classmethod
    def strength(cls, password: str) -> dict:
        score = 0
        notes: list[str] = []
        if not password:
            return {"score": 0, "crack_time": "instantly", "notes": ["empty"]}
        if password.lower() in cls.COMMON:
            return {"score": 2, "crack_time": "instantly", "notes": ["top-common password"]}
        length = len(password)
        score += min(40, length * 4)
        classes = sum(bool(re.search(p, password)) for p in
                      (r"[a-z]", r"[A-Z]", r"\d", r"[^A-Za-z0-9]"))
        score += classes * 12
        if length >= 16:
            score += 8
        if re.search(r"(.)\1\1", password):
            score -= 12
            notes.append("repeated characters")
        if re.search(r"(012|123|234|345|678|abc|qwe|asd)", password.lower()):
            score -= 10
            notes.append("sequential pattern")
        score = max(0, min(100, score))
        entropy_bits = length * (3.32 * classes) if classes else 1
        guesses = 2 ** entropy_bits
        # assume 10^10 guesses/sec offline attacker
        seconds = guesses / 1e10
        score = min(score, int(min(100, 20 + entropy_bits * 2.2)))
        return {"score": score, "crack_time": cls._human_time(seconds), "notes": notes}

    @staticmethod
    def _human_time(seconds: float) -> str:
        for unit, div in (("years", 31_536_000), ("days", 86_400), ("hours", 3_600),
                          ("minutes", 60)):
            if seconds >= div:
                return f"{seconds / div:.1f} {unit}"
        return f"{seconds:.1f} seconds"

    @staticmethod
    async def breached(password: str) -> bool | None:
        """HIBP k-anonymity: only the first 5 SHA-1 chars are sent. None = lookup failed."""
        try:
            import aiohttp

            sha1 = hashlib.sha1(password.encode()).hexdigest().upper()
            prefix, suffix = sha1[:5], sha1[5:]
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as http:
                async with http.get(f"https://api.pwnedpasswords.com/range/{prefix}") as resp:
                    if resp.status != 200:
                        return None
                    text = await resp.text()
            for line in text.splitlines():
                if line.split(":")[0].strip() == suffix:
                    return True
            return False
        except Exception:  # noqa: BLE001
            return None


# ══════════════════════════════════════════════════════════════
# Profile security scoring (public-signal heuristic)
# ══════════════════════════════════════════════════════════════
class ProfileSecurityScorer:
    """
    Compute a 0-100 security score from PUBLIC signals only:

    + private account                +25
    + verified                       +15
    + no email exposed in bio        +20
    + no phone exposed in bio        +20
    + no external link in bio        +10
    + reasonable username length     +10
    """

    @staticmethod
    def score(profile: dict) -> dict:
        factors: list[tuple[str, bool | None]] = []
        private = bool(profile.get("private"))
        verified = bool(profile.get("verified"))
        emails = profile.get("emails") or []
        phones = profile.get("phones") or []
        bio_link = profile.get("bio_link")
        uname = profile.get("username") or ""

        factors.append(("private_account", private))
        factors.append(("verified", verified))
        factors.append(("no_email_in_bio", not emails))
        factors.append(("no_phone_in_bio", not phones))
        factors.append(("no_bio_link", bio_link is None))
        factors.append(("username_hard_to_guess", len(uname) >= 8 and not re.fullmatch(r"[a-z]+\d{0,3}", uname)))

        weights = {"private_account": 25, "verified": 15, "no_email_in_bio": 20,
                   "no_phone_in_bio": 20, "no_bio_link": 10, "username_hard_to_guess": 10}
        total = sum(weights[name] for name, ok in factors if ok is True)
        return {"score": total, "factors": factors}


__all__ = [
    "AES256Cipher", "Roles", "RoleUtils", "sync_role_cache", "RateLimiter",
    "TwoFactor", "PasswordAnalyzer", "ProfileSecurityScorer",
]
