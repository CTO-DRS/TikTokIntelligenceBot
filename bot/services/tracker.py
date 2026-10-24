"""
Tracking service — periodic snapshots + change detection with notifications.

Event bitmask:
    0x01 username change      0x02 bio change        0x04 avatar change
    0x08 followers ±10%       0x10 new video         0x20 verified change
"""
from __future__ import annotations

import hashlib
import json

from bot.services.tiktok_api import TikTokClient
from bot.utils.logger import get_logger
from database.models import AccountSnapshot
from database.repository import Repository

log = get_logger(__name__)

E_USERNAME = 0x01
E_BIO = 0x02
E_AVATAR = 0x04
E_FOLLOWERS10 = 0x08
E_NEW_VIDEO = 0x10
E_VERIFIED = 0x20


class TrackingService:
    def __init__(self, repo: Repository, client: TikTokClient | None = None):
        self.repo = repo
        self.client = client or TikTokClient()

    # ── snapshot helpers ─────────────────────────────────────
    async def take_snapshot(self, profile: dict) -> AccountSnapshot:
        videos = profile.get("videos") or []
        views = sum(int(v.get("views") or 0) for v in videos)
        extras = {
            "nickname": profile.get("nickname"),
            "bio_hash": hashlib.sha256((profile.get("bio") or "").encode()).hexdigest()[:16],
            "avatar": (profile.get("avatar") or "")[:200],
            "verified": bool(profile.get("verified")),
            "last_video_id": (videos[0].get("id") if videos else None),
        }
        return await self.repo.add_snapshot(
            tiktok_username=profile.get("username") or "unknown",
            followers=int(profile.get("followers") or 0),
            following=int(profile.get("following") or 0),
            likes=int(profile.get("likes") or 0),
            video_count=int(profile.get("videos_count") or 0),
            views=views,
            extras=extras,
        )

    # ── change detection ─────────────────────────────────────
    async def check_account(self, tracked, lang: str = "ar") -> list[dict]:
        """Fetch one tracked account, diff against the last snapshot → notifications."""
        username = tracked.tiktok_username
        notifications: list[dict] = []
        result = await self.client.fetch_profile(username, want_videos=5)
        if not result.ok:
            return notifications
        profile = result.data
        snap = await self.take_snapshot(profile)

        last = await self.repo.latest_snapshot(username)
        prev = None
        if last and last.id != snap.id:
            prev = last
        if prev is None or prev.extras_json is None:
            return notifications

        try:
            prev_extras = json.loads(prev.extras_json or "{}")
        except json.JSONDecodeError:
            prev_extras = {}

        events = tracked.events_mask
        current_username = profile.get("username") or username

        # username change
        if events & E_USERNAME:
            old_name = prev.tiktok_username
            if old_name and current_username and old_name.lower() != current_username.lower():
                notifications.append(self._msg(
                    tracked.telegram_user_id,
                    f"🔁 @{old_name} → @{current_username}\n(Username changed)"))
        # bio change
        if events & E_BIO:
            old_bio = prev_extras.get("bio_hash")
            new_bio = hashlib.sha256((profile.get("bio") or "").encode()).hexdigest()[:16]
            if old_bio and old_bio != new_bio:
                notifications.append(self._msg(
                    tracked.telegram_user_id,
                    f"📝 Bio changed for @{current_username}:\n{profile.get('bio') or '—'}"))
        # avatar change
        if events & E_AVATAR:
            old_avatar = prev_extras.get("avatar")
            new_avatar = (profile.get("avatar") or "")[:200]
            if old_avatar and old_avatar != new_avatar:
                notifications.append(self._msg(
                    tracked.telegram_user_id, f"🖼 Avatar changed for @{current_username}"))
        # followers ±10%
        if events & E_FOLLOWERS10 and prev.followers:
            change = (snap.followers - prev.followers) / prev.followers
            if abs(change) >= 0.10:
                arrow = "📈" if change > 0 else "📉"
                notifications.append(self._msg(
                    tracked.telegram_user_id,
                    f"{arrow} @{current_username}: {prev.followers:,} → {snap.followers:,} "
                    f"({change * 100:+.1f}% followers)"))
        # new video
        if events & E_NEW_VIDEO:
            old_vid = prev_extras.get("last_video_id")
            new_vid = (profile.get("videos") or [{}])[0].get("id")
            if old_vid and new_vid and str(old_vid) != str(new_vid):
                notifications.append(self._msg(
                    tracked.telegram_user_id,
                    f"🎬 New video on @{current_username}!"))
        # verified change
        if events & E_VERIFIED:
            old_v = prev_extras.get("verified")
            new_v = bool(profile.get("verified"))
            if old_v is not None and old_v != new_v:
                notifications.append(self._msg(
                    tracked.telegram_user_id,
                    f"✔️ Verification {'granted ✅' if new_v else 'removed ❌'} for @{current_username}"))
        return notifications

    async def check_all(self) -> list[dict]:
        """Run over every active tracked account (used by job queue & Celery)."""
        tracked_rows = await self.repo.list_tracked(only_active=True)
        notifications: list[dict] = []
        for row in tracked_rows:
            try:
                notifications.extend(await self.check_account(row))
            except Exception as exc:  # noqa: BLE001
                log.warning("track check failed for @%s: %s", row.tiktok_username, exc)
        return notifications

    @staticmethod
    def _msg(telegram_id: int, text: str) -> dict:
        return {"telegram_id": telegram_id, "text": "🔔 Tracking alert\n" + text}


__all__ = ["TrackingService", "E_USERNAME", "E_BIO", "E_AVATAR",
           "E_FOLLOWERS10", "E_NEW_VIDEO", "E_VERIFIED"]
