# 📖 User Manual — TikTok Intelligence Bot

> Version: 1.0 — Updated: 2026-10
> For end users. Technical details: `API_DOCUMENTATION.md` · Deployment: `DEPLOYMENT_GUIDE.md`.

---

## 1. Introduction

**TikTok Intelligence Bot** is a Telegram bot that analyses **public** TikTok accounts and produces detailed Arabic/English reports. It reads only what any visitor can see on a profile, never hacks anything, and **never fabricates data** — any field that cannot be legitimately obtained is shown as **"Unavailable"** with a reason.

What makes this bot different from "black magic" tools:
- Full transparency: every field is labelled ✅ available / 🧮 estimated / ⛔ unavailable.
- Real math (engagement rate, best posting hours, hashtag analysis) — not random numbers.
- Time-series tracking builds a follower-growth history and draws a 30-day curve.

### 1.1 What can you actually learn about a public account?

| Information | Status |
|---|---|
| Name, handle, bio, avatar, verification, private/public, declared region | ✅ Available |
| Followers, following, total hearts, video count | ✅ Available |
| Last 30 videos: views, likes, comments, shares, saves, duration, music, hashtags | ✅ Available |
| Engagement rate, avg views, best posting hours, keywords, content categories | ✅ Computed |
| Email/phone **explicitly written in the bio**, or links to other platforms | ⚠️ Only if present |
| Follower growth (30-day curve) | 🧮 Builds over time via `/track` |
| Fake-follower share (heuristic) | 🧮 Low-confidence estimate |
| Audience country/age/gender splits | 🧮 Low-confidence estimate (TikTok only shares these with the account owner) |
| Creation IP/GPS, registered email/phone, Device/Session ID, password, breach history, username history | ⛔ Unavailable — server-side private data; no public API exists, and obtaining it would be illegal |

---

## 2. Getting Started

1. Open the chat with the bot (link provided by the bot owner).
2. Send `/start` — the main menu with inline buttons appears.
3. Pick your language in `/settings` (Arabic by default, English fully supported).

### 2.1 Three detail levels
From `/settings` → Detail level:

| Level | For | Shows |
|---|---|---|
| `basic` | Casual users | Essentials only: name, followers, hearts, headline numbers |
| `advanced` | Most users | All sections with analytics |
| `full` | Analysts | Everything + technical fields + per-field availability/confidence notes |

---

## 3. The 17 Commands

### 3.1 Scanning
| Command | Usage | Description |
|---|---|---|
| `/scan` | `/scan username`, `/scan @username`, or a video URL | Instant scan at your chosen detail level |
| `/deepscan` | `/deepscan username` | Deep scan: 30-video analysis, best hours, hashtags, keywords, content categories, music, account security analysis |
| `/bulk` | `/bulk user1 user2 ...` | Bulk scan up to 25 accounts — one message per result |
| `/compare` | `/compare user1 user2` | Side-by-side diff table with % deltas |
| `/track` | `/track username` | Toggle tracking: alerts on name/bio/avatar change, verification, new video, ±10% followers |

> 💡 You can always send a **TikTok video URL** instead of a username in `/scan`.

### 3.2 Reports & data
| Command | Usage | Description |
|---|---|---|
| `/report` | `/report username [pdf|html|xlsx|json]` | Full report delivered as a file. Arabic RTL PDF; Excel with native charts |
| `/history` | `/history` | Your last 10 scans with dates and types |
| `/export` | `/export` | Export all your stored data as JSON (your GDPR right) |
| `/stats` | `/stats` | Your usage stats: scan count, last activity, active tracks |

### 3.3 Admin commands
| Command | Description |
|---|---|
| `/admin` | Control panel: broadcast, cleanup, system status |
| `/broadcast <text>` | Message all users (with confirmation step) |
| `/block <telegram_id>` | Ban a user |
| `/unblock <telegram_id>` | Unban |
| `/stats_all` | Global stats: users, scans, tracks |
| `/clean` | Purge data older than retention (30 days default) |

### 3.4 Settings
`/settings` → Language (AR/EN) · Detail level (3 levels) · Tracking notifications on/off.

---

## 4. Interactive Menus (3 levels)

`/start` opens an inline-button menu system with Back/Close buttons on every level:

```
🏠 Main menu
├── 🔎 Quick scan      → type a username (or paste a video URL)
├── 🔬 Deep scan
├── ⚖️ Compare         → type: user1 user2
├── 🔔 Tracking        → my tracks / add track
├── 📄 Reports         → choose format → account
├── 🗂 History
├── ⚙️ Settings        → language / detail level / notifications
└── 🛡 Admin panel     (admins only)
```

---

## 5. Reading a Scan Result

Every section is labelled:
- ✅ **Available** — real data fetched now.
- 🧮 **Estimated** — statistical model on public data, with a confidence level (high/medium/low).
- ⛔ **Unavailable** — with a **clear reason** (e.g. "server-side private data — no public API").

Example excerpt:

```
📊 Statistics
  Followers:        1.2M
  Total hearts:     34.5M
  Engagement rate:  4.8% (very good for this follower tier)

📈 Follower growth (30 days)
  🧮 Estimated — needs ≥2 snapshots
  💡 Enable /track username to start building history

📱 Device & location
  ⛔ Device ID: unavailable — server-side private data
  Declared region: SA ✅
  Timezone (inferred): Asia/Riyadh 🧮 (medium confidence)
```

### 5.1 Confidence levels of geo inference
The geolocation module never knows a user's real location — it infers:

| Source | Confidence |
|---|---|
| `region` field from profile data | High |
| Timezone inferred from region | Medium |
| Bio language/link analysis | Low |
| Video `locationCreated` if present | Medium |

---

## 6. Tracking & Alerts

When you `/track username`:
- Every **10 minutes** the bot checks the account and alerts you on: name/bio/avatar change, verification gained/lost, new video, **±10%** follower change.
- Every **hour** a snapshot is stored feeding the 30-day growth curve in reports.
- Send `/track username` again to stop tracking (toggle).
- Temporarily mute alerts from `/settings` without losing history.

---

## 7. Reports

| Format | Best for |
|---|---|
| `pdf` | Formal presentation — Arabic RTL, cover, tables, growth chart, disclaimer |
| `html` | Browser — single styled page, printable |
| `xlsx` | Working the data — separate sheets + native Excel charts |
| `json` | Programmatic use — full structure with per-field status |

Files arrive directly in the chat.

---

## 8. Privacy & Your Rights

- The bot stores: your Telegram ID, username, language, command history, your scan results.
- `/export` gives you a full JSON copy of your data; `/clean` (admin) auto-purges old records (30 days default, configurable).
- Sensitive values (e.g. admin 2FA secrets) are encrypted with AES-256-GCM and never displayed.
- Never share passwords or OTP codes with the bot — **it will never ask for them**.

---

## 9. FAQ

**Q: Why do I see "Unavailable" so often in advanced sections?**
A: Those fields (IP, GPS, registration email, Device ID…) are private server-side data no public API provides. The bot is honest instead of selling you fabricated numbers.

**Q: Sometimes results are labelled "demo data" — why?**
A: When TikTok rate-limits requests, the bot serves clearly-labelled demo data instead of failing silently, so you can still test the UI. Retry shortly for real data.

**Q: Does it matter if I type `@` or paste a full link?**
A: No. Input is normalised: `username` / `@username` / profile link / video link all work.

**Q: Can I scan a private account?**
A: Only its public shell (name, avatar, handle, private status) — never content.

**Q: How is engagement rate computed?**
A: (likes + comments + shares + saves) over recent videos ÷ average views — a view-based ER is more realistic than a follower-based one.

**Q: Deep scan is slow?**
A: It fetches and analyses 30 videos; a few seconds is normal. Abuse protection limits it to 5 runs/hour (configurable).

---

## 10. Responsible Use
Use the bot for legitimate analysis (marketing, research, journalism, security). Prohibited: stalking individuals, profiling children, or any use violating TikTok ToS or your local law (GDPR etc.). The operator is responsible for lawful deployment.
