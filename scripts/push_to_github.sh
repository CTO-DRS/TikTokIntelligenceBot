#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# push_to_github.sh — رفع المشروع إلى GitHub بأمان
# الاستخدام:
#   ./scripts/push_to_github.sh <TOKEN> [REPO_URL]
# مثال:
#   ./scripts/push_to_github.sh github_pat_xxxx https://github.com/CTO-DRS/TikTokIntelligenceBot.git
#
# ملاحظات أمنية:
#   * التوكن يُستخدم في الذاكرة فقط ولن يُكتب في أي ملف أو في الـ remote.
#   * استخدم Fine-grained token بصلاحية Contents: Read & Write فقط.
#   * لا تشارك التوكن في المحادثات — أنشئه من:
#     GitHub → Settings → Developer settings → Personal access tokens
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

TOKEN="${1:-}"
REPO="${2:-https://github.com/CTO-DRS/TikTokIntelligenceBot.git}"

if [[ -z "$TOKEN" ]]; then
  echo "✗ الاستخدام: $0 <TOKEN> [REPO_URL]"; exit 1
fi

cd "$(git rev-parse --show-toplevel 2>/dev/null || echo .)"

# remote بدون توكن (التوكن يُمرر مؤقتاً في أمر الدفع فقط)
git remote remove origin 2>/dev/null || true
git remote add origin "$REPO"

BRANCH="$(git rev-parse --abbrev-ref HEAD || echo main)"
BRANCH="${BRANCH:-main}"

echo "→ Pushing $(git rev-list --count HEAD) commit(s) on '$BRANCH' to $REPO"
git -c credential.helper= push "https://x-access-token:${TOKEN}@$(echo "$REPO" | sed 's#https://##')" "$BRANCH"

# تنظيف: أزل أي بقايا توكن من تكوين git
git remote set-url origin "$REPO"
echo "✓ تم الرفع بنجاح — التوكن لم يُحفظ في أي مكان."
