# 🚀 Deployment Guide — TikTok Intelligence Bot

> Covers: local dev, Docker Compose production, webhook + Nginx + TLS, horizontal scaling, blue-green deployment, backups & monitoring.
> Arabic version first, then the same content in English.

---

## الجزء الأول — بالعربية

### 1. المتطلبات
- خادم Linux (Ubuntu 22.04+ / Debian 12) بذاكرة 2GB+ (يُفضّل 4GB مع Grafana).
- Docker 24+ و Docker Compose v2.
- دومين موجّه للخادم إذا كنت ستستخدم Webhook (موصى به للإنتاج).
- توكن بوت من [@BotFather] ومعرف مشرفك من [@userinfobot].

### 2. الإعداد الأساسي
```bash
git clone https://github.com/CTO-DRS/TikTokIntelligenceBot.git
cd TikTokIntelligenceBot

cp docker/.env.example docker/.env
# عدّل docker/.env:
#   BOT_TOKEN=...            إلزامي
#   ADMIN_USER_IDS=...       إلزامي
#   ENCRYPTION_KEY=...       ولّده بالأمر تحت
#   WEBHOOK_URL=https://bot.example.com   (اختياري — إنتاج)

python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"
```

### 3. تشغيل الإنتاج (Docker Compose)
```bash
docker compose -f docker/docker-compose.yml --env-file docker/.env up -d --build
docker compose -f docker/docker-compose.yml ps        # تأكد أن كل الخدمات healthy
docker compose -f docker/docker-compose.yml logs -f bot
```
الخدمات: `postgres` (16) · `redis` (7) · `bot` · `worker` (Celery) · `beat` · `nginx` · `prometheus` · `grafana`.

المنافذ الافتراضية: Nginx `:80` → webhook · Prometheus `:9090` · Grafana `:3000` · مقاييس البوت الداخلية `:9091/metrics`.

> ⚙️ **وضعين للتشغيل:**
> - **Polling** (الافتراضي بدون WEBHOOK_URL): البوت يوصل لتيليجرام بنفسه — مناسب للتطوير أو الشبكات المفتوحة.
> - **Webhook** (الإنتاج): أضف `WEBHOOK_URL` وسيخدم البوت على `http://0.0.0.0:8080` خلف Nginx.

### 4. TLS عبر Caddy (أسهل طريقة)
```bash
# أمام nginx، أو استبدل nginx بـ Caddy مباشرة:
docker run -d --name caddy --network host \
  -v caddy_data:/data caddy:2 \
  caddy reverse-proxy --from bot.example.com --to 127.0.0.1:80
```
أو استخدم certbot مع nginx التقليدي. تيليجرام يقبل فقط 443, 80, 88, 8443 للـ webhook.

### 5. التشغيل بدون Docker (تطوير)
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/migrate.py                 # إنشاء الجداول
python bot/main.py                        # البوت (SQLite تلقائياً إن لم يوجد POSTGRES_HOST)
celery -A bot.tasks worker -l info -B     # اختياري: worker مع beat مدمج
```
> بدون Redis يعمل البوت أيضاً: RateLimiter يتحول تلقائياً للذاكرة.

### 6. التوسع الأفقي (Horizontal Scaling)
- **البوت (webhook)**: شغّل عدة نسخ خلف Nginx مع `ip_hash` أو موازن عادي — webhook عديم الحالة. مع polling لا تُشغّل أكثر من نسخة واحدة (تعارض getUpdates).
- **Celery workers**: زيادة النسخ آمنة تماماً: `docker compose up -d --scale worker=4` (اضبط `worker_concurrency` حسب الذاكرة).
- **PostgreSQL**: نقطة الاحتكار الأولى — استخدم managed DB (RDS/CloudSQL) قبل التوسع الجاد.
- **الجلسات/الحالة**: كل الحالة في Postgres/Redis، لذا النسخ متكافئة (stateless).

### 7. النشر الأزرق-الأخضر (Blue-Green)
```bash
# 1) جهّز الإصدار الجديد بجانب القديم
docker compose -f docker/docker-compose.yml --env-file docker/.env \
  -p tiktok-green up -d --build bot worker beat

# 2) اختبر الإصدار الأخضر
docker compose -p tiktok-green logs -f bot
# أرسل /scan للبوت وتأكد من صحة النتائج

# 3) بدّل المرور (Nginx upstream أو سحب/رفع حاوية بالاسم القديم)
docker stop tiktok-blue-bot-1 && docker rm tiktok-blue-bot-1

# 4) أوقف الإصدار الأزرق القديم
docker compose -p tiktok-blue down
```
ملاحظات:
- قاعدة البيانات تُدار بترحيلات متوافقة للأمام — شغّل `python scripts/migrate.py` (أو حاوية واحدة) قبل تبديل المرور.
- Redis/Postgres مشتركة بين الأزرق والأخضر (نفس الشبكة أو external networks).

### 8. النسخ الاحتياطي والاسترجاع
- تلقائي: Celery `backup_database` كل 6 ساعات → `data/backups/` مع احتفاظ 14 يوماً.
- يدوي: `python scripts/backup.py`
- استرجاع: `psql -U tiktok -d tiktok_intel < backups/backup_YYYYMMDD_HHMM.sql` (أو `sqlite3 data/bot.db < ...`).
- انسخ `docker/.env` و `data/backups/` إلى مخزن خارجي (S3/rclone) — ليسا ضمن git.

### 9. المراقبة والسجلات
- Grafana `:3000` (admin/admin — **غيّر كلمة المرور فوراً**)، مصدر Prometheus جاهز.
- Sentry: ضع `SENTRY_DSN` في `docker/.env` ثم أعد تشغيل البوت.
- السجلات بصيغة JSON — جاهزة لـ Loki/ELK: `docker compose logs -f --format json`.

### 10. تحديث المشروع
```bash
git pull origin main
docker compose -f docker/docker-compose.yml --env-file docker/.env up -d --build
```

---

# Part 2 — English

### 1. Requirements
- Linux server (Ubuntu 22.04+/Debian 12), 2GB+ RAM (4GB recommended with Grafana).
- Docker 24+, Compose v2.
- A domain (recommended for webhook mode).
- Bot token from @BotFather, your admin Telegram ID from @userinfobot.

### 2. Setup
```bash
git clone https://github.com/CTO-DRS/TikTokIntelligenceBot.git
cd TikTokIntelligenceBot
cp docker/.env.example docker/.env    # fill BOT_TOKEN, ADMIN_USER_IDS
python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"  # ENCRYPTION_KEY
```

### 3. Production (Docker Compose)
```bash
docker compose -f docker/docker-compose.yml --env-file docker/.env up -d --build
docker compose -f docker/docker-compose.yml ps
docker compose -f docker/docker-compose.yml logs -f bot
```
Services: `postgres`, `redis`, `bot`, `worker`, `beat`, `nginx`, `prometheus`, `grafana`.
Ports: Nginx `:80` (webhook path) · Prometheus `:9090` · Grafana `:3000` · bot metrics `:9091/metrics`.

**Modes:** *Polling* by default (no `WEBHOOK_URL`) — fine for dev. *Webhook* for production: set `WEBHOOK_URL`, bot serves `:8080` behind Nginx. Telegram accepts only ports 443/80/88/8443 for webhooks; terminate TLS with Caddy/certbot.

### 4. Local dev (no Docker)
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/migrate.py
python bot/main.py                      # SQLite fallback, Redis optional
celery -A bot.tasks worker -l info -B   # optional
```
No Redis? The rate limiter transparently falls back to in-memory.

### 5. Horizontal Scaling
- **Bot (webhook)**: stateless — run N replicas behind Nginx (`ip_hash` or round-robin). Never run two polling instances.
- **Celery**: `docker compose up -d --scale worker=4`.
- **PostgreSQL**: first bottleneck — move to managed DB before serious scaling.
- All shared state lives in Postgres/Redis → replicas are equivalent.

### 6. Blue-Green Deployment
```bash
# 1) start green next to blue
docker compose -f docker/docker-compose.yml --env-file docker/.env \
  -p tiktok-green up -d --build bot worker beat
# 2) smoke-test green (send /scan)
# 3) switch traffic (nginx upstream / container rename)
docker stop tiktok-blue-bot-1 && docker rm tiktok-blue-bot-1
# 4) retire blue
docker compose -p tiktok-blue down
```
Notes: run migrations **before** switching traffic; keep DB/Redis shared across colors.

### 7. Backups & Recovery
- Automatic: `backup_database` Celery task every 6h → `data/backups/` (14-day retention).
- Manual: `python scripts/backup.py`
- Restore: `psql -U tiktok -d tiktok_intel < backups/backup_....sql`
- Offsite-copy `docker/.env` + `data/backups/` (S3/rclone) — never committed to git.

### 8. Monitoring & Logs
- Grafana `:3000` (admin/admin — **change it**), Prometheus datasource pre-provisioned.
- Sentry via `SENTRY_DSN`. Logs are JSON — pipe to Loki/ELK directly.

### 9. Updating
```bash
git pull origin main
docker compose -f docker/docker-compose.yml --env-file docker/.env up -d --build
```

### 10. Security Checklist (production)
- [ ] `ENCRYPTION_KEY` generated and stored in a secret manager.
- [ ] Grafana default password changed; dashboards behind auth/VPN if public.
- [ ] Nginx only exposes the webhook path; Prometheus/Grafana firewalled or behind SSO.
- [ ] `POSTGRES_PASSWORD` strong and unique.
- [ ] Server SSH key-only login, ufw allowing 22/80/443 only.
