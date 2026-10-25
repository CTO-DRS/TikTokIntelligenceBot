# 🤖 TikTok Intelligence Bot — بوت تيك توك للاستخبارات

[![CI](https://github.com/CTO-DRS/TikTokIntelligenceBot/actions/workflows/ci.yml/badge.svg)](https://github.com/CTO-DRS/TikTokIntelligenceBot/actions/workflows/ci.yml)
![Version](https://img.shields.io/badge/version-1.1.0-fe2c55)
![Tests](https://img.shields.io/badge/tests-41%20pass-25f4ee)

<p align="center">
  <b>بوت تيليجرام متكامل لتحليل وتتبع حسابات تيك توك</b><br>
  <i>A complete Telegram bot for TikTok account intelligence, analytics & tracking</i>
</p>

---

## ⚠️ إطار النزاهة: ما الذي يمكن الحصول عليه فعلاً؟ / Data Honesty First

هذا البوت **لا يخترق** تيك توك ولا يصل إلى أي بيانات خاصة. يقرأ **البيانات العامة فقط**.
قبل استخدام أي أداة مماثلة، افهم هذه المصفوفة:

| الحقل / Field | الحالة | الشرح / Why |
|---|---|---|
| الاسم، المعرّف، النبذة، الصورة، التوثيق، خاص/عام، البلد (region) | ✅ متاح | بيانات الملف العام |
| المتابعون، المتابَعون، الإعجابات، عدد الفيديوهات | ✅ متاح | عدّادات عامة |
| آخر 30 فيديو (مشاهدات، إعجابات، تعليقات، مشاركات، الموسيقى، الهاشتاقات) | ✅ متاح | محتوى عام |
| الإيميل/الهاتف **المكتوبة في النبذة** | ⚠️ إذا وُجدت | استخراج بنمط Regex من bio |
| روابط انستغرام/يوتيوب/تويتر في النبذة | ⚠️ إذا وُجدت | parsing عام |
| أفضل وقت نشر، معدل التفاعل، تحليل الهاشتاقات | ✅ محسوب | تحليل رياضي على بيانات عامة |
| نمو المتابعين 30 يوم | ⚠️ تدريجي | يحتاج snapshots عبر الزمن |
| نسبة الف مكذب/الجغرافيا/الأعمار/الجنس للجمهور | ⚠️ تقدير منخفض الثقة | تيك توك لا ينشرها إلا لصاحب الحساب |
| **IP الإنشاء، GPS الإنشاء، إيميل الحساب، رقم الهاتف، Device ID، Session ID، كلمة المرور، سجل الاختراق، تاريخ التوثيق، تاريخ إنشاء الحساب بالساعة، سجل أسماء المستخدمين، الموقع الجغرافي للفيديو** | ❌ غير متاح | بيانات خاصة/سيرفرية — لا يوجد أي API عام يوفرها، ومحاولة الحصول عليها تُعد اختراقاً ومخالفة قانونية |

> 🔎 عند عدم توفر حقل يعرضه البوت كـ **"غير متوفر"** مع سبب واضح — **لا يخترع بيانات أبداً**.
> This bot never fabricates data: unavailable fields are explicitly marked as N/A with a reason.

---

## ✨ المزايا / Features

- 📊 **فحص فوري** `/scan` — كل الحقول العامة + معدل التفاعل
- 🔬 **فحص عميق** `/deepscan` — تحليل 30 فيديو + أفضل أوقات النشر + الهاشتاقات + الكلمات المفتاحية + تصنيف المحتوى + تحليل أمني
- 📦 **فحص جماعي** `/bulk` — حتى 25 حساباً بالتوازي
- ⚖️ **مقارنة** `/compare` — جدول فروقات بين حسابين
- 🔔 **تتبع** `/track` — تنبيهات: تغيّر الاسم/النبذة/الصورة، توثيق، فيديو جديد، ±10% متابعين
- 📄 **تقارير** `/report` — PDF (عربي RTL) + HTML + Excel (مع رسوم بيانية) + JSON (مخطط إصداري v1.1 مع خريطة توفر كل حقل)
- 📈 **رسوم بيانية تلقائية** مع `/deepscan` — منحنى نمو المتابعين 30 يوماً، خريطة حرارية لأوقات النشر، أعمدة الهاشتاقات، دونات التفاعل (تسميات عربية مع تراجع تلقائي للإنجليزية)
- 🌐 **وحدة جغرافيا وأجهزة** — تحليل User-Agent / Headers / IP→Geo (geopy + reverse_geocoder + timezonefinder) بمنهجية صادقة
- 🗂 **قوائم 3 مستويات** بأزرار داخلية + تبديل عربي/إنجليزي + 3 مستويات تفصيل (مبسط/متقدم/خبير)
- 🛡 **أمان**: AES-256-GCM، 5 أدوار، Rate Limiting متعدد الطبقات (Redis)، سجل تدقيق، كشف محاولات الحقن، 2FA للمشرفين (TOTP)
- ⚙️ **تشغيل**: Docker Compose + Nginx + Celery + Redis + PostgreSQL + Prometheus + Grafana + Sentry

## 🧱 البنية / Architecture

```
Telegram ⇄ Nginx ⇄ python-telegram-bot (bot/main.py)
                        │
        ┌───────────────┼────────────────┐
   services/        database/         reports/
   tiktok_api       PostgreSQL/SQLite  PDF/HTML/Excel/JSON
   geolocation      SQLAlchemy
   analytics        repository.py
   security  ─── Redis (cache + rate-limit)
   tracker    ─── Celery (bot/tasks.py) → backups / cleanup / tracking digest
                        │
              Prometheus + Grafana + Sentry + ELK (اختياري)
```

## 🚀 التشغيل السريع / Quick Start

### 1) متطلبات / prerequisites
Python 3.11+ و Docker.

### 2) الإعداد
```bash
cp docker/.env.example docker/.env
# ثم عدّل BOT_TOKEN (من @BotFather) و ADMIN_USER_IDS (من @userinfobot)
# ولّد مفتاح التشفير:
python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"
```

### 3) التثبيت والتشغيل
```bash
pip install -r requirements.txt
python scripts/migrate.py
docker-compose -f docker/docker-compose.yml --env-file docker/.env up -d
python bot/main.py
celery -A bot.tasks worker --loglevel=info
```
> ℹ️ ملف compose موضوع داخل `docker/` حسب هيكل المشروع، لذا نمرر `-f`.
> للتطوير المحلي بدون Docker: البوت يعمل تلقائياً على SQLite + Redis اختياري (fallback للذاكرة).

### 4) الأوامر الـ17
| أمر | وصف | أمر | وصف |
|---|---|---|---|
| `/start` | قائمة رئيسية تفاعلية | `/settings` | اللغة ومستوى التفصيل |
| `/scan` | فحص حساب | `/export` | تصدير بياناتك JSON |
| `/deepscan` | فحص عميق + تحليلات | `/admin` | لوحة المشرف |
| `/bulk` | فحص جماعي | `/broadcast` | رسالة جماعية (مشرف) |
| `/compare` | مقارنة حسابين | `/block` | حظر مستخدم (مشرف) |
| `/track` | تتبع حساب | `/unblock` | رفع الحظر (مشرف) |
| `/stats` | إحصائياتك | `/stats_all` | إحصائيات عامة (مشرف) |
| `/report` | توليد تقرير | `/clean` | تنظيف البيانات القديمة (مشرف) |
| `/history` | سجل فحوصاتك | | |

## 🔐 الأمان / Security
- تشفير AES-256-GCM لأي بيانات حساسة + مفتاح خارج الكود.
- 5 أدوار: BANNED < USER < VIP < ADMIN < SUPER_ADMIN.
- حد استخدام متعدد الطبقات (كل أمر/دقيقة/ساعة) عبر Redis بنافذة منزلقة.
- تسجيل تدقيق لكل عملية إدارية + كشف حقن SQL/XSS على المدخلات.
- 2FA (TOTP) اختياري للمشرفين.
- نسخ احتياطي كل 6 ساعات (Celery Beat) مع احتفاظ 14 يوماً.

## 📈 المراقبة / Monitoring
- Prometheus: `http://<host>:9091/metrics` — Grafana: `http://<host>:3000` (admin/admin — غيّرها).
- Sentry عبر `SENTRY_DSN`. سجلات JSON جاهزة لـ Logstash/Elasticsearch.

## 🧪 الاختبارات
```bash
pytest tests/ -v        # 41 اختباراً
make test               # أو عبر Makefile
```

## 📚 التوثيق الكامل / Documentation
| الملف | المحتوى |
|---|---|
| [`docs/USER_MANUAL_AR.md`](docs/USER_MANUAL_AR.md) | دليل المستخدم بالعربية (17 أمراً، القوائم، الأسئلة الشائعة) |
| [`docs/USER_MANUAL_EN.md`](docs/USER_MANUAL_EN.md) | English user manual |
| [`docs/API_DOCUMENTATION.md`](docs/API_DOCUMENTATION.md) | مرجع الوحدات والدوال + عقد صدق البيانات |
| [`docs/DEPLOYMENT_GUIDE.md`](docs/DEPLOYMENT_GUIDE.md) | النشر: Docker، Webhook+Nginx+TLS، التوسع الأفقي، النشر الأزرق-الأخضر |
| [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md) | استكشاف الأخطاء وإصلاحها (عَرَض ← سبب ← حل) |
| [`CHANGELOG.md`](CHANGELOG.md) | سجل الإصدارات |

## 📜 الترخيص والاستخدام المسؤول
MIT — لكن **مسؤوليتك القانونية عليك**: التزم بشروط خدمة تيك توك وقوانين الخصوصية (GDPR وغيرها).
لا تستخدم البوت للتتبع المسيء أو استخراج بيانات الأطفال أو أي غرض غير قانوني.

<p align="center"><b>Made with ❤️ — Arabic & English supported</b></p>
