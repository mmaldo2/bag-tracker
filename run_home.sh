#!/usr/bin/env bash
# Runs the Depop + Mercari pass from a home machine and syncs state with the repo.
# Schedule it hourly (cron on macOS/Linux; on this machine a Hermes cron job, see notes/hermes-handoff.md).
# Secrets: put DISCORD_WEBHOOK_URL / SMTP_* / VERDICT_* in a file called .env next to this script.
set -euo pipefail
cd "$(dirname "$0")"
[ -f .env ] && set -a && . ./.env && set +a
PY=python3
[ -x .venv/Scripts/python.exe ] && PY=.venv/Scripts/python.exe
[ -x .venv/bin/python ] && PY=.venv/bin/python
git config merge.jsonstate.driver "\"$PY\" merge_state.py %O %A %B"
git rebase --abort >/dev/null 2>&1 || true     # never stay wedged from a previous run
git pull --rebase --autostash --quiet
"$PY" sync_verdicts.py
"$PY" tracker.py --sources home
for f in state/seen.json state/verdicts.json docs/finds.json docs/verdicts.json; do
  [ -f "$f" ] && git add "$f"
done
git diff --cached --quiet && exit 0
git commit -qm "state(home): $(date -u +%Y-%m-%dT%H:%MZ)"
for i in 1 2 3; do
  git pull --rebase --quiet && git push --quiet && exit 0
  sleep 5
done
echo "run_home: push failed after 3 attempts; will retry next run" >&2
exit 1
