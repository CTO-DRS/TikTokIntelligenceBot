"""
Async repository — the single data-access boundary (Repository pattern).

Every table mutation goes through this class; handlers never touch sessions.
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from bot.utils.logger import get_logger
from config.settings import Settings, get_settings
from database.models import (
    AccountSnapshot,
    AuditLog,
    Base,
    ReportFile,
    ReportKind,
    Role,
    SavedProfile,
    ScanRecord,
    ScanType,
    TGUser,
    TrackedAccount,
    utcnow,
)

log = get_logger(__name__)


class Repository:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._engine: AsyncEngine = create_async_engine(
            self.settings.get_database_url(), pool_pre_ping=True, echo=False
        )
        self._session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    # ── infrastructure ───────────────────────────────────────
    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self._session_factory() as session:
            yield session

    async def init_models(self, drop: bool = False) -> None:
        async with self.engine.begin() as conn:
            if drop:
                await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        log.info("database schema ready")

    async def dispose(self) -> None:
        await self._engine.dispose()

    # ── users ────────────────────────────────────────────────
    async def ensure_user(self, telegram_id: int, username: str | None = None,
                          first_name: str | None = None) -> TGUser:
        async with self.session() as s:
            user = (await s.execute(select(TGUser).where(TGUser.telegram_id == telegram_id))).scalar_one_or_none()
            if user is None:
                user = TGUser(
                    telegram_id=telegram_id,
                    username=username,
                    first_name=first_name,
                    language=self.settings.default_language,
                    role=Role.SUPER_ADMIN if telegram_id in self.settings.admin_ids else Role.USER,
                )
                s.add(user)
                await s.commit()
                await s.refresh(user)
            else:
                if username:
                    user.username = username
                if first_name:
                    user.first_name = first_name
                user.last_seen = utcnow()
                await s.commit()
            return user

    async def get_user(self, telegram_id: int) -> TGUser | None:
        async with self.session() as s:
            return (await s.execute(select(TGUser).where(TGUser.telegram_id == telegram_id))).scalar_one_or_none()

    async def set_language(self, telegram_id: int, lang: str) -> None:
        await self._update_user_fields(telegram_id, language=lang)

    async def set_detail_level(self, telegram_id: int, level: str) -> None:
        await self._update_user_fields(telegram_id, detail_level=level)

    async def set_role(self, telegram_id: int, role: Role) -> None:
        await self._update_user_fields(telegram_id, role=role)

    async def set_two_fa_secret(self, telegram_id: int, encrypted_secret: str) -> None:
        await self._update_user_fields(telegram_id, two_fa_secret=encrypted_secret)

    async def list_users(self, limit: int = 500) -> list[TGUser]:
        async with self.session() as s:
            return list((await s.execute(select(TGUser).order_by(TGUser.id.desc()).limit(limit))).scalars())

    async def count_users(self) -> int:
        async with self.session() as s:
            return int((await s.execute(select(func.count(TGUser.id)))).scalar_one())

    async def _update_user_fields(self, telegram_id: int, **fields: Any) -> None:
        async with self.session() as s:
            await s.execute(update(TGUser).where(TGUser.telegram_id == telegram_id).values(**fields))
            await s.commit()

    # ── scans ────────────────────────────────────────────────
    async def add_scan(self, telegram_user_id: int, target_username: str, scan_type: ScanType,
                       status: str = "OK", duration_ms: int = 0, result_path: str | None = None) -> ScanRecord:
        async with self.session() as s:
            rec = ScanRecord(
                telegram_user_id=telegram_user_id,
                target_username=target_username,
                scan_type=scan_type,
                status=status,
                duration_ms=duration_ms,
                result_path=result_path,
            )
            s.add(rec)
            await s.commit()
            await s.refresh(rec)
            return rec

    async def recent_scans(self, telegram_user_id: int, limit: int = 10) -> list[ScanRecord]:
        async with self.session() as s:
            q = (select(ScanRecord)
                 .where(ScanRecord.telegram_user_id == telegram_user_id)
                 .order_by(ScanRecord.id.desc())
                 .limit(limit))
            return list((await s.execute(q)).scalars())

    async def user_scan_count(self, telegram_user_id: int) -> int:
        async with self.session() as s:
            q = select(func.count(ScanRecord.id)).where(ScanRecord.telegram_user_id == telegram_user_id)
            return int((await s.execute(q)).scalar_one())

    async def add_report(self, *, kind: ReportKind, path: str, size_bytes: int,
                         telegram_user_id: int | None = None, scan_id: int | None = None) -> ReportFile:
        async with self.session() as s:
            rec = ReportFile(kind=kind, path=path, size_bytes=size_bytes,
                             telegram_user_id=telegram_user_id, scan_id=scan_id)
            s.add(rec)
            await s.commit()
            await s.refresh(rec)
            return rec

    # ── tracking & snapshots ─────────────────────────────────
    async def track_account(self, telegram_user_id: int, tiktok_username: str,
                            events_mask: int = 0x3F) -> TrackedAccount:
        async with self.session() as s:
            row = (await s.execute(
                select(TrackedAccount).where(
                    TrackedAccount.telegram_user_id == telegram_user_id,
                    TrackedAccount.tiktok_username == tiktok_username,
                )
            )).scalar_one_or_none()
            if row:
                row.is_active = True
                row.events_mask = events_mask
            else:
                row = TrackedAccount(telegram_user_id=telegram_user_id,
                                     tiktok_username=tiktok_username, events_mask=events_mask)
                s.add(row)
            await s.commit()
            await s.refresh(row)
            return row

    async def untrack_account(self, telegram_user_id: int, tiktok_username: str) -> bool:
        async with self.session() as s:
            res = await s.execute(
                delete(TrackedAccount).where(
                    TrackedAccount.telegram_user_id == telegram_user_id,
                    TrackedAccount.tiktok_username == tiktok_username,
                )
            )
            await s.commit()
            return (res.rowcount or 0) > 0

    async def list_tracked(self, telegram_user_id: int | None = None,
                           only_active: bool = True) -> list[TrackedAccount]:
        async with self.session() as s:
            q = select(TrackedAccount)
            if telegram_user_id is not None:
                q = q.where(TrackedAccount.telegram_user_id == telegram_user_id)
            if only_active:
                q = q.where(TrackedAccount.is_active.is_(True))
            return list((await s.execute(q)).scalars())

    async def count_tracked(self) -> int:
        async with self.session() as s:
            return int((await s.execute(select(func.count(TrackedAccount.id)))).scalar_one())

    async def add_snapshot(self, tiktok_username: str, followers: int, following: int,
                           likes: int, video_count: int, views: int,
                           extras: dict | None = None) -> AccountSnapshot:
        async with self.session() as s:
            snap = AccountSnapshot(
                tiktok_username=tiktok_username,
                followers=followers,
                following=following,
                likes=likes,
                video_count=video_count,
                views=views,
                extras_json=json.dumps(extras or {}, ensure_ascii=False),
                captured_at=utcnow(),
            )
            s.add(snap)
            await s.commit()
            await s.refresh(snap)
            return snap

    async def latest_snapshot(self, tiktok_username: str) -> AccountSnapshot | None:
        async with self.session() as s:
            q = (select(AccountSnapshot)
                 .where(AccountSnapshot.tiktok_username == tiktok_username)
                 .order_by(AccountSnapshot.captured_at.desc())
                 .limit(1))
            return (await s.execute(q)).scalar_one_or_none()

    async def snapshots(self, tiktok_username: str, days: int = 30) -> list[AccountSnapshot]:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        async with self.session() as s:
            q = (select(AccountSnapshot)
                 .where(AccountSnapshot.tiktok_username == tiktok_username,
                        AccountSnapshot.captured_at >= since)
                 .order_by(AccountSnapshot.captured_at.asc()))
            return list((await s.execute(q)).scalars())

    # ── audit & admin ────────────────────────────────────────
    async def audit(self, actor_id: int | None, action: str,
                    payload: str | None = None, ip: str | None = None) -> None:
        async with self.session() as s:
            s.add(AuditLog(actor_id=actor_id, action=action, payload=payload, ip=ip))
            await s.commit()

    async def global_stats(self) -> dict:
        async with self.session() as s:
            users = int((await s.execute(select(func.count(TGUser.id)))).scalar_one())
            scans = int((await s.execute(select(func.count(ScanRecord.id)))).scalar_one())
            today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            scans_today = int((await s.execute(
                select(func.count(ScanRecord.id)).where(ScanRecord.created_at >= today)
            )).scalar_one())
            tracked = int((await s.execute(select(func.count(TrackedAccount.id)))).scalar_one())
            reports = int((await s.execute(select(func.count(ReportFile.id)))).scalar_one())
            top = (await s.execute(
                select(ScanRecord.target_username, func.count(ScanRecord.id).label("c"))
                .group_by(ScanRecord.target_username)
                .order_by(func.count(ScanRecord.id).desc()).limit(1)
            )).first()
            return {"users": users, "scans": scans, "today": scans_today,
                    "tracked": tracked, "reports": reports,
                    "top": f"@{top[0]}" if top else "—"}

    async def cleanup(self, scan_days: int, snapshot_days: int) -> int:
        """Retention purge; returns deleted scan rows count."""
        scan_cutoff = datetime.now(timezone.utc) - timedelta(days=scan_days)
        snap_cutoff = datetime.now(timezone.utc) - timedelta(days=snapshot_days)
        async with self.session() as s:
            r1 = await s.execute(delete(ScanRecord).where(ScanRecord.created_at < scan_cutoff))
            await s.execute(delete(AccountSnapshot).where(AccountSnapshot.captured_at < snap_cutoff))
            await s.commit()
            return int(r1.rowcount or 0)


# ── process-wide singleton ───────────────────────────────────
_repo: Repository | None = None


def get_repository() -> Repository:
    global _repo
    if _repo is None:
        _repo = Repository(get_settings())
    return _repo
