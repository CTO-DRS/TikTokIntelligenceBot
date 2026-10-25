# 🔧 Troubleshooting / استكشاف الأخطاء وإصلاحها

> Format: **Symptom → Cause → Fix** · التنسيق: **العَرَض ← السبب ← الحل**

---

## 1. Bot does not start / البوت لا يبدأ

### `BOT_TOKEN is empty`
- **Cause:** `docker/.env` missing or empty `BOT_TOKEN`.
- **Fix:** `cp docker/.env.example docker/.env`, fill token from @BotFather, restart.
- Compose users: ensure `--env-file docker/.env` is passed (compose file lives in `docker/`).

### `TelegramInvalidToken` / 401 on start
- Token revoked or copied with spaces. Regenerate in @BotFather → API Token.

### Bot starts but nothing responds
- Polling conflict: **two instances with the same token** → both fight over `getUpdates`. Stop the other (old container, local run, another server).
  ```bash
  docker ps | grep bot        # find duplicates
  curl -s "https://api.telegram.org/bot<TOKEN>/getWebhookInfo"
  # If webhook is set, polling won't receive updates (and vice-versa)
  ```

---

## 2. Webhook problems / مشاكل الويب هوك

### Commands work locally, not on server (or vice versa)
- `getWebhookInfo` shows `last_error_message`: usually **SSL** or **wrong port**.
- Telegram only accepts ports **443, 80, 88, 8443**. Set `WEBHOOK_URL=https://domain` (no port/path needed beyond the secret path the bot appends).
- Nginx must proxy to bot container port `8080`:
  ```nginx
  location /tg-webhook { proxy_pass http://bot:8080; proxy_set_header Host $host; }
  ```
- After changing `WEBHOOK_URL`, restart the bot — it re-registers the webhook.

### 404/403 on webhook URL
- The secret path must match `WEBHOOK_SECRET`. Empty secret defaults to `tg-webhook`.

---

## 3. Database / قاعدة البيانات

### `can't open file 'data/bot.db'` or permission denied (SQLite)
- Run `python scripts/migrate.py` once; ensure the process user can write `data/`.

### `connection refused 5432` (Docker)
- Postgres not healthy yet: `docker compose logs postgres` — wait for `database system is ready`.
- In containers always use host `postgres` (service name), not `localhost`.

### `password authentication failed`
- You changed `POSTGRES_PASSWORD` **after** the volume was created. Either keep the old password or recreate the volume (**data loss**):
  ```bash
  docker compose down -v   # ⚠️ deletes DB data
  ```
- Prefer: `ALTER USER tiktok WITH PASSWORD 'new';` inside psql then update `.env`.

### Tables missing / `relation does not exist`
- The bot auto-creates tables in `post_init`; if you skipped it, run `python scripts/migrate.py`.

---

## 4. Redis / Celery

### `Redis is down — falling back to memory`
- Expected graceful degradation: rate limiting becomes per-process. Restart Redis: `docker compose up -d redis`.
- Verify: `docker compose exec redis redis-cli ping` → `PONG`.

### Celery worker doesn't pick tasks
- Run beat too: `celery -A bot.tasks beat` (or embed: `worker -B`).
- Broker mismatch: worker and bot must resolve the same `REDIS_URL`.
- Inspect queue: `docker compose exec redis redis-cli llen celery`.

### Tasks run but no Telegram alerts
- Worker process needs outbound access to `api.telegram.org`; check egress firewall/proxy.
- See worker logs: `docker compose logs -f worker`.

---

## 5. TikTok scraping / جمع البيانات

### Results labelled "demo data"
- TikTok blocked the request (rate-limit/geo/missing cookie). Fixes, in order:
  1. Wait 10–30 min (blocks are usually temporary).
  2. Set `TIKTOK_SESSIONID` cookie from a logged-in browser session (improves stability a lot).
  3. Set `SCRAPING_PROXY` to a residential/HTTP proxy close to your users.
  4. Increase `SCRAPING_TIMEOUT` if the network is slow.
- The bot never crashes on this — `result.demo=True` and the UI labels it.

### `result.ok == False` for a valid username
- Username typo (the cleaner strips `@`, links, and junk — check what it resolved to).
- Account renamed — search by the new handle.
- Region-blocked collector → try proxy.

### Profile works but videos list empty
- Account has 0 posts, or only `web-videos` blocked → enable session cookie.

---

## 6. Reports / التقارير

### PDF has boxes/garbled Arabic (□□□)
- Server lacks Arabic fonts. Docker image ships Noto Naskh; for bare-metal:
  ```bash
  apt install fonts-noto-core   # Debian/Ubuntu — يضم Noto Naskh/Sans Arabic
  fc-cache -f
  ```

### Excel file opens with warnings
- Old Excel versions complain about generated files; update Office or use LibreOffice.

### Report not sent / file too big
- Very long deep-scans can exceed Telegram 50MB only in pathological cases; check `data/reports/` exists and is writable.

---

## 7. Performance / الأداء

### Slow /scan under load
- DB pool exhaustion: raise `pool_size` in `database/database.py`.
- Too many concurrent deep-scans: lower `RATE_LIMIT_DEEP_HOUR`, scale workers (`--scale worker=4`).

### Prometheus page empty on :9091
- `METRICS_ENABLED=false` in env, or another process took the port — change `METRICS_PORT`.

### High memory in grafana
- Cap retention or disable grafana if you don't need dashboards: `docker compose stop grafana`.

---

## 8. Security issues / أمان

### "banned" for everyone
- `ADMIN_USER_IDS` wrong → nobody is admin, and if a ban was issued against a user id it persists in DB. Fix admins list; use `/unblock <id>`.

### 2FA locked out an admin
- Delete the stored secret (encrypted) from DB row `tg_users.two_fa_secret` via psql, or re-provision TOTP.

### Suspicious payloads logged (IDS)
- `detect_injection` logs and blocks SQL/XSS-like input — check logs for the pattern source; usually a user testing the bot. Persistent abusers: `/block`.

---

## 9. Docker quick diagnosis / تشخيص سريع
```bash
docker compose -f docker/docker-compose.yml ps              # statuses
docker compose -f docker/docker-compose.yml logs --tail=100 bot
docker compose -f docker/docker-compose.yml logs --tail=100 worker
docker compose -f docker/docker-compose.yml exec postgres psql -U tiktok -d tiktok_intel -c '\dt'
docker compose -f docker/docker-compose.yml exec redis redis-cli ping
curl -s http://localhost:9091/metrics | head                 # bot metrics
curl -s "https://api.telegram.org/bot<TOKEN>/getMe"
```

## 10. Still stuck؟
1. Collect: `docker compose ps` + last 200 log lines + your `docker/.env` **without secrets**.
2. Open an issue on GitHub with the above.
3. للدعم بالعربية ارفق اللقطات أعلاه مع وصف الخطوات التي أدت للمشكلة.
