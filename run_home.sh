#!/usr/bin/env bash
# Runs the Depop + Mercari pass from a home machine and syncs state with the repo.
# Schedule it (every 30 min is plenty):
#   crontab -e   →   */30 * * * * /path/to/bag-tracker/run_home.sh >> /path/to/bag-tracker/state/home.log 2>&1
# Secrets: put DISCORD_WEBHOOK_URL (and any others) in a file called .env next to this script.
set -euo pipefail
cd "$(dirname "$0")"
[ -f .env ] && set -a && . ./.env && set +a
git pull --rebase --quiet
python3 tracker.py --sources home
git add state/seen.json
git diff --cached --quiet || { git commit -qm "state(home): $(date -u +%Y-%m-%dT%H:%MZ)"; git push --quiet; }
