# Changelog

All notable changes to this project are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/) · Versioning: [SemVer](https://semver.org/).

## [1.1.0] — 2026-10-24

### Added
- **Documentation suite** (`docs/`): bilingual user manuals (AR/EN), full API reference,
  deployment guide (webhook + Nginx + TLS, horizontal scaling, blue-green deployment,
  backups) and troubleshooting playbook.
- **Chart service** (`bot/services/charts.py`): publication-quality PNG charts —
  follower-growth line (30-day snapshots), posting heatmap (DOW×hour avg views),
  top-hashtags bar, engagement-mix donut. Arabic labels reshaped+bidi with automatic
  Arabic-font discovery and graceful English fallback. Built exclusively with
  `constrained_layout=True` (no conflicting layout calls).
- **Deep-scan visual analytics**: `/deepscan` now attaches up to 3 charts as photos
  after the text result (failures logged & skipped — never fatal).
- **Canonical JSON report** (`reports/generators/json_generator.py` v1.1): versioned
  schema with honesty legend, per-field availability metadata and a machine-readable
  `data_integrity` tally. `/report … json` now uses it.
- **CI pipeline** (`.github/workflows/ci.yml`): Python 3.11/3.12 matrix — byte-compile,
  import smoke test (18 commands), pytest suite, Docker image build, compose config
  validation.
- **Project tooling**: `Makefile` (install/migrate/bot/worker/beat/test/compose/backup),
  `.dockerignore`, `VERSION`, this changelog.
- **14 new tests** (`test_charts.py`, `test_json_generator.py`) — suite now 41 tests.

### Changed
- `/report … json` output upgraded to the canonical v1.1 schema (was ad-hoc inline dump).
- `perform_scan` captures the analytics result explicitly for chart rendering.

### Notes
- No breaking changes to DB schema or callback data formats.

## [1.0.0] — 2026-10 (de28e17)

### Added
- Complete codebase: 17 commands (+/help), 3-level inline menus, AR/EN i18n,
  TikTok public-data collector with honesty-first availability labels,
  analytics engine, geolocation/device modules, AES-256-GCM security,
  5 roles, Redis sliding-window rate limiting, TOTP 2FA, tracking with
  change alerts, snapshot series, PDF/HTML/Excel reports, Celery beat jobs
  (tracking/snapshots/backup/cleanup/weekly digest), Docker Compose stack
  (postgres, redis, bot, worker, beat, nginx, prometheus, grafana),
  Prometheus metrics, Sentry, JSON logs, migration/backup/cleanup scripts,
  25 unit tests.
