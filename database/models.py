"""
SQLAlchemy 2.0 models (async-ready).

Tables
------
TGUser           telegram users, roles, language, detail level
ScanRecord       every scan performed (who / whom / type / status)
TrackedAccount   watchlist entries with an event bitmask
AccountSnapshot  periodic metric snapshots powering 30-day growth charts
ReportFile       generated report artefacts
AuditLog         admin/security actions trail
SavedProfile     user's pinned accounts
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum as PyEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Role(PyEnum):
    BANNED = "BANNED"
    USER = "USER"
    VIP = "VIP"
    ADMIN = "ADMIN"
    SUPER_ADMIN = "SUPER_ADMIN"


class ScanType(PyEnum):
    BASIC = "BASIC"
    DEEP = "DEEP"
    BULK = "BULK"
    COMPARE = "COMPARE"


class ReportKind(PyEnum):
    PDF = "PDF"
    HTML = "HTML"
    EXCEL = "EXCEL"
    JSON = "JSON"


class TGUser(Base):
    __tablename__ = "tg_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str | None] = mapped_column(String(128))
    language: Mapped[str] = mapped_column(String(5), default="ar", nullable=False)
    role: Mapped[Role] = mapped_column(Enum(Role, name="role_enum"), default=Role.USER, nullable=False)
    detail_level: Mapped[str] = mapped_column(String(10), default="advanced", nullable=False)
    two_fa_secret: Mapped[str | None] = mapped_column(String(64))  # stored AES-encrypted
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ScanRecord(Base):
    __tablename__ = "scan_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tg_users.telegram_id", ondelete="CASCADE"), index=True
    )
    target_username: Mapped[str] = mapped_column(String(64), index=True)
    scan_type: Mapped[ScanType] = mapped_column(Enum(ScanType, name="scan_type_enum"), default=ScanType.BASIC)
    status: Mapped[str] = mapped_column(String(16), default="OK")  # OK | FAIL | DEMO
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    result_path: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class TrackedAccount(Base):
    __tablename__ = "tracked_accounts"
    __table_args__ = (UniqueConstraint("telegram_user_id", "tiktok_username", name="uq_track"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tg_users.telegram_id", ondelete="CASCADE"), index=True
    )
    tiktok_username: Mapped[str] = mapped_column(String(64), index=True)
    events_mask: Mapped[int] = mapped_column(Integer, default=0x3F)  # all events by default
    last_snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("account_snapshots.id", ondelete="SET NULL"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AccountSnapshot(Base):
    __tablename__ = "account_snapshots"
    __table_args__ = (Index("ix_snap_user_time", "tiktok_username", "captured_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tiktok_username: Mapped[str] = mapped_column(String(64))
    followers: Mapped[int] = mapped_column(BigInteger, default=0)
    following: Mapped[int] = mapped_column(BigInteger, default=0)
    likes: Mapped[int] = mapped_column(BigInteger, default=0)
    video_count: Mapped[int] = mapped_column(Integer, default=0)
    views: Mapped[int] = mapped_column(BigInteger, default=0)
    extras_json: Mapped[str | None] = mapped_column(Text)  # nickname/bio hash/avatar/verified
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReportFile(Base):
    __tablename__ = "report_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scan_id: Mapped[int | None] = mapped_column(ForeignKey("scan_records.id", ondelete="SET NULL"))
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    kind: Mapped[ReportKind] = mapped_column(Enum(ReportKind, name="report_kind_enum"))
    path: Mapped[str] = mapped_column(String(512))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class SavedProfile(Base):
    __tablename__ = "saved_profiles"
    __table_args__ = (UniqueConstraint("telegram_user_id", "tiktok_username", name="uq_saved"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tg_users.telegram_id", ondelete="CASCADE"), index=True
    )
    tiktok_username: Mapped[str] = mapped_column(String(64))
    note: Mapped[str | None] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
