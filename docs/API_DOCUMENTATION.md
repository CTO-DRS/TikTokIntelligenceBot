# 🧬 API Documentation — TikTok Intelligence Bot

> Audience: developers extending or integrating with this codebase.
> All services are async-first (aiohttp + SQLAlchemy 2.0 async) except pure-math analyzers which are static/sync.
> Data-honesty contract: every produced field carries an availability status — see §1.

---

## 1. Data Honesty Contract (`DataAvailability`)

All collector/analyzer outputs are annotated with `bot/services/tiktok_api.DataAvailability`:

| Status | Meaning | UI marker |
|---|---|---|
| `AVAILABLE` | Real data fetched from a public source | ✅ |
| `ESTIMATED` | Statistical model over public data; see `confidence` (`high|medium|low`) | 🧮 |
| `UNAVAILABLE` | Server-side/private data — never fabricated | ⛔ |

`FieldMeta` wraps a value: `{"value": ..., "status": ..., "confidence": ..., "reason": ...}`.
**Rule:** adding a new field requires declaring its availability — the formatters, PDF/HTML/Excel generators and the JSON report all render these labels.

---

## 2. Collector — `bot/services/tiktok_api.py`

```python
from bot.services.tiktok_api import TikTokClient, ProfileResult

client = TikTokClient()                      # reads config.settings
result: ProfileResult = await client.fetch_profile("username", want_videos=30)
result.ok          # bool — True if a public profile was resolved
result.demo        # bool — True if clearly-labelled demo fallback was served
result.source      # str — which source won (html-embed / universal-data / demo)
result.data        # dict — normalized profile (below)
await client.close()
```

### 2.1 `fetch_profile(username, want_videos=None)`
Resolution chain (first success wins):
1. **TikTok web HTML** → parse `__UNIVERSAL_DATA_FOR_REHYDRATION__` / `SIGI_STATE` JSON.
2. **oEmbed** (`https://www.tiktok.com/oembed?url=…`) → display-name/avatar fallback.
3. **Demo profile** (`demo_profile`) — only if `settings.demo_fallback=True`; `result.demo=True` and all fields labelled accordingly.

### 2.2 Normalized profile keys
```python
{
  "username": str, "nickname": str|None, "user_id": str|None, "sec_uid": str|None,
  "avatar": str|None, "bio": str|None, "bio_link": str|None,
  "verified": bool|None, "private": bool|None,
  "followers": int|None, "following": int|None, "hearts": int|None, "video_count": int|None,
  "region": str|None, "language": str|None,
  "create_time": int|None,          # unix — only if present in public payload
  "socials": {"instagram": ..., "youtube": ..., "twitter": ...},   # from bio/bio_link
  "emails": [...], "phones": [...],                                  # only if written in bio
  "videos": [ { "id", "create_time", "duration", "views", "likes",
                "comments", "shares", "bookmarks", "desc", "hashtags": [...],
                "music_title", "music_author", "location", "cover" } ],  # normalized by _normalize_video
  "meta": { field: {"status", "confidence", "reason"} , ... }
}
```
Errors: returns `ProfileResult(ok=False, error=...)` — **never raises** to handlers.

---

## 3. Analytics Engine — `bot/services/analytics.py`

```python
from bot.services.analytics import AnalyticsEngine
engine = AnalyticsEngine(snapshots=snapshot_rows)   # rows of AccountSnapshot
analysis = engine.analyze(profile)                  # mutates profile with flattened stats too
```

| Component | Method | Returns |
|---|---|---|
| `EngagementAnalyzer` | `summarize(profile)` | `total_views, avg_views, avg_likes, avg_comments, avg_shares, engagement_rate (view-based), er_level` |
| `ContentAnalyzer` | `best_posting_hours(videos, top=5)` | `[{"hour": 20, "dow": 6, "avg_views": 512k, "samples": n}]` |
| | `hashtag_analysis(videos, top=12)` | `[(tag, count)]` |
| | `keyword_extraction(videos, top=12)` | `[(word, count)]` (stop-word filtered) |
| | `classify_content(videos)` | category histogram from keyword buckets |
| | `music_analysis(videos, top=8)` | `[{"title", "author", "count"}]` |
| `FollowerAnalytics` | `growth_30d(snapshots)` | `{"sufficient", "points": [(iso, followers)], "delta_30d", "note"}` — needs ≥2 snapshots |
| | `fake_follower_estimate(profile)` | low-confidence heuristic with explicit factors breakdown |
| `AudienceAnalytics` | `audience(profile)` | country/age/gender estimates or `UNAVAILABLE` — never fabricated |
| `CompareService` | `diff(a, b)` | rows `(label, value_a, value_b, delta%)` |

---

## 4. Geolocation & Devices — `bot/services/geolocation.py`

> ⚠️ **Privacy stance:** this module never learns a user's real location. It processes only caller-provided signals (an IP, HTTP headers, a User-Agent, or public profile fields) and labels every inference with confidence.

```python
from bot.services.geolocation import GeolocationFacade
facade = GeolocationFacade()
report = await facade.full_analysis(ip="1.2.3.4", headers={...}, profile=profile_dict)
# report = {"ip": GeoResult|None, "device": DeviceInfo, "inferences": [...]}
```

| Class | Method | Purpose |
|---|---|---|
| `IPGeolocation` | `await locate(ip)` | IP → country/city/lat-lon/timezone/ISP via provider chain (ip-api → ipwho.is), `GeoResult.gps` masked property |
| `UserAgentAnalyzer` | `parse(ua)` | TikTok/normal UA → `DeviceInfo{os, os_version, brand, model, app_version, ...}` |
| `HeaderAnalyzer` | `parse(headers)` | device signals from HTTP headers (X-Requested-With, carrier hints…) |
| `DeviceInfoExtractor` | `from_payload(payload)` | device fields inside JSON payloads; `mask_device_id()` masks all but last 4 chars |
| `GeolocationFacade` | `await full_analysis(...)` | orchestrates all above + profile-based inferences (`region` → timezone → city, bio-language heuristic) |

`GeoResult.as_dict()` / `DeviceInfo.as_dict()` → JSON-safe dicts with per-field `status/confidence`.

---

## 5. Security — `bot/services/security.py`

| Class | API | Notes |
|---|---|---|
| `AES256Cipher` | `encrypt(str)->str`, `decrypt(str)->str` | AES-256-GCM, key = base64 32 bytes from `ENCRYPTION_KEY`; random nonce per message |
| `Roles` / `RoleUtils` | `role_of(tid)`, `is_banned(tid)` | in-memory role cache; `sync_role_cache(tid, role_name)` called at startup |
| `RateLimiter` | `await allow(key, limit, window_seconds)->bool` | Redis sliding window (`ZSET`); **graceful memory fallback** if Redis is down |
| `TwoFactor` | `new_secret()`, `provisioning_uri(secret, account)`, `verify(secret, code)` | TOTP (pyotp) for admins |
| `PasswordAnalyzer` | `strength(pwd)`, `await breached(pwd)` | zxcvbn-style scoring + HIBP k-anonymity (returns `None` if API unreachable) |
| `ProfileSecurityScorer` | `score(profile)->{"score": 0-100, "factors": [...]}` | public-exposure scoring of the scanned account |

### Decorators — `bot/utils/decorators.py`
```python
@guard("scan", limit=15, window="hour")   # role gate + rate limit + audit in one
@admin_only                                # requires ADMIN/SUPER_ADMIN
@banned_guard                              # rejects banned users
@async_safe(default=None)                  # swallows unexpected errors (logs them)
```

---

## 6. Tracking — `bot/services/tracker.py`

```python
service = TrackingService(repo, client=None)          # client auto-built
await service.take_snapshot(profile) -> AccountSnapshot   # hourly series
notes = await service.check_account(tracked, lang="ar")   # list of {"telegram_id","text"}
notes = await service.check_all()                          # full sweep (Celery/job-queue entry)
```
Alert triggers: username/nickname/bio/avatar change, verification toggle, new video, follower change ≥10%.

---

## 7. Database Layer — `database/`

### 7.1 Models (`database/models.py`)
`TGUser`, `ScanRecord`, `TrackedAccount`, `AccountSnapshot`, `ReportFile`, `AuditLog`, `SavedProfile`.
Enums: `Role(banned<user<vip<admin<super_admin)`, `ScanType`, `ReportKind`.
`AccountSnapshot` powers 30-day growth: `tiktok_username, followers, following, hearts, video_count, captured_at`.

### 7.2 Repository (`database/repository.py`) — key methods
```python
repo = get_repository()                        # process-wide singleton
await repo.init_models(drop=False)             # create tables (DDL)
async with repo.session() as s: ...            # raw session escape hatch
await repo.ensure_user(tid, username, full_name)  # upsert on any interaction
await repo.set_language/set_detail_level/set_role(tid, ...)
await repo.add_scan(tid, target, ScanType.SCAN, success=..., duration_ms=...)
await repo.recent_scans(tid, limit=10); repo.user_scan_count(tid)
await repo.track_account(tid, username) / untrack_account / list_tracked / count_tracked
await repo.add_snapshot(username, followers, following, hearts, video_count)
await repo.snapshots(username, days=30); repo.latest_snapshot(username)
await repo.audit(actor_id, action, details=...)
await repo.global_stats()                      # for /stats_all
await repo.cleanup(scan_days=30, snapshot_days=180) -> int
```
URL resolution: `DATABASE_URL` env → else `POSTGRES_*` → else SQLite `data/bot.db` (zero-config dev).

---

## 8. Report Generators — `reports/generators/`

```python
from reports.generators.pdf_generator import PDFReport
from reports.generators.html_generator import HTMLReport
from reports.generators.excel_generator import ExcelReport
from reports.generators.json_generator import JSONReport      # added v1.1

PDFReport(lang="ar").build(profile, analytics, out_path)               # Arabic RTL, growth chart
HTMLReport(lang="ar").build(profile, analytics, out_path)              # single-page, embedded CSS
ExcelReport(lang="ar").build(profile, analytics, snapshots, out_path)  # sheets + native charts
JSONReport().build(profile, analytics, out_path)                       # canonical machine format
```
All generators: `build(...)` never raises on partial data (renders “unavailable” rows), and all include the honesty legend + disclaimer.

---

## 9. Formatters / i18n / Validators — `bot/utils/`

```python
from bot.utils.formatters import build_profile_message, build_compare_message, build_history_message
from bot.utils.i18n import t
from bot.utils.validators import clean_username, sanitize_text, detect_injection, extract_emails, extract_phones, safe_filename

t("ar", "scan_done", username=user)          # nested dict translations ar/en
build_profile_message(profile, lang, level)  # basic|advanced|full — HTML parse-mode text
clean_username("@https://vt.tiktok.com/…")   # normalizes @, links, junk → "username"
detect_injection(payload)                    # SQL/XSS prompt-injection heuristic (IDS)
```

---

## 10. Bot Layer

### 10.1 Entry — `bot/main.py`
`create_app()` wires: 18 command handlers (`commands.COMMANDS` incl. `/help`) → callback router (group 1) → text router (group 2) → global error handler. `post_init` sets commands, creates tables, syncs role cache, starts in-process tracking/snapshot jobs (no Celery needed for single instance) and Prometheus exporter `:9091/metrics`.
Polling by default; `WEBHOOK_URL` (+ optional `WEBHOOK_SECRET`) switches to webhook mode.

### 10.2 Callback & text routers — `bot/handlers/`
`callbacks.callback_router` — menu navigation (3 levels), language/detail toggles, admin confirms.
`messages.text_router` — contextual free-text (awaited username, compare pairs, broadcast text) with IDS filtering (`detect_injection`).

### 10.3 Celery — `bot/tasks.py` (`celery -A bot.tasks`)
| Task | Schedule | Job |
|---|---|---|
| `check_tracked_changes` | 10 min | tracker sweep → Telegram alerts |
| `snapshot_watchlist` | hourly :05 | snapshots → growth series |
| `backup_database` | */6h :30 | backup + 14-day retention |
| `cleanup_old_data` | daily 03:00 | retention purge |
| `weekly_digest` | Sat 09:00 | usage digest to admins |

Run: worker `celery -A bot.tasks worker -l info` · beat `celery -A bot.tasks beat` (or `worker -B`).

---

## 11. Configuration Reference (`config/settings.py`)

| Env var | Default | Purpose |
|---|---|---|
| `BOT_TOKEN` | — (required) | from @BotFather |
| `ADMIN_USER_IDS` | — | comma-separated admin telegram ids |
| `DATABASE_URL` | sqlite | full async URL override (asyncpg driver) |
| `POSTGRES_HOST/PORT/USER/PASSWORD/DB` | localhost/5432/tiktok/tiktok_secret/tiktok_intel | used when DATABASE_URL empty |
| `REDIS_HOST/PORT/DB`, `REDIS_URL` | localhost/6379/0 | rate-limit cache; Celery broker |
| `ENCRYPTION_KEY` | — | base64(32 random bytes) for AES-256 |
| `WEBHOOK_URL`, `WEBHOOK_PORT`, `WEBHOOK_SECRET` | ""/8080/"" | webhook mode (empty → polling) |
| `RATE_LIMIT_SCAN_HOUR/DEEP_HOUR/BULK_HOUR/REPORT_HOUR/GLOBAL_MINUTE` | 15/5/2/8/20 | abuse protection |
| `TikTOK_SESSIONID` → `TIKTOK_SESSIONID` | "" | optional cookie improving stability |
| `SCRAPING_TIMEOUT/RETRIES/PROXY` | 25/3/"" | collector tuning |
| `DEMO_FALLBACK` | true | serve labelled demo data when blocked |
| `VIDEOS_DEEP_COUNT` | 30 | deep-scan video window |
| `SCAN_RETENTION_DAYS`, `SNAPSHOT_RETENTION_DAYS`, `BACKUP_RETENTION_DAYS` | 30/180/14 | retention |
| `SENTRY_DSN`, `METRICS_ENABLED`, `METRICS_PORT`, `LOG_LEVEL` | ""/true/9091/INFO | observability |
| `DEFAULT_LANGUAGE` | ar | ar/en |

---

## 12. Extension Recipes

**Add a new scan field**
1. Collect in `TikTokClient._normalize_*` (or a new service).
2. Annotate with `FieldMeta` status — if private, `UNAVAILABLE` + reason.
3. Render in `formatters.build_profile_message` + generators.

**Add a new analyzer**
- Static classmethod in `analytics.py` returning plain dicts; wire into `AnalyticsEngine.analyze`; it will automatically reach all report formats.

**Add a new command**
1. `async def cmd_x(update, context)` in `commands.py`, decorated `@guard("x", limit, window)` (admins: `@admin_only`).
2. Register in `COMMANDS` dict + `BotCommand` list in `main.py` + translations in `i18n.py`.

**Add a new alert type**
- Extend `TrackingService.check_account` diff table; keep `_msg()` shape `{"telegram_id", "text"}`.
