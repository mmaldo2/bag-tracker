#!/usr/bin/env bash
# Runs the Depop + Mercari pass from a home machine and syncs state with the repo.
# Schedule it every 30 minutes (cron on macOS/Linux, Task Scheduler on Windows; see README).
# Secrets: put DISCORD_WEBHOOK_URL / SMTP_* / VERDICT_* in a file called .env next to this script.
set -euo pipefail
cd "$(dirname "$0")"
[ -f .env ] && set -a && . ./.env && set +a
PY=python3
[ -x .venv/Scripts/python.exe ] && PY=.venv/Scripts/python.exe
[ -x .venv/bin/python ] && PY=.venv/bin/python
git pull --rebase --quiet
"$PY" sync_verdicts.py
"$PY" tracker.py --sources home
git add state/seen.json state/verdicts.json docs/finds.json docs/verdicts.json 2>/dev/null || true
git diff --cached --quiet || { git commit -qm "state(home): $(date -u +%Y-%m-%dT%H:%MZ)"; git push --quiet; }
