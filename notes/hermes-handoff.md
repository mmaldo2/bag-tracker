# Handoff to Hermes: schedule the bag tracker's home runner

## What you are being asked to do

Create ONE recurring Hermes cron job that runs an existing shell script every 30 minutes with
no model involved (`--no-agent`), trigger it once, and confirm it worked. Nothing else.

## Facts

- Repo (already cloned, on `main`, clean): `C:\Users\marcu\Documents\Bag search tracker\bag-tracker`
- Script to run: `run_home.sh` in that folder. It does: `git pull --rebase --autostash`, pulls her
  swipe verdicts from a Cloudflare Worker, runs `tracker.py --sources home` (Depop + Mercari via
  headless browsers), then commits and pushes `state/seen.json`, `state/verdicts.json`,
  `docs/finds.json`, `docs/verdicts.json` to GitHub. A run takes 3 to 5 minutes.
- It must run from a residential IP on this machine (Depop and Mercari block datacenter IPs)
  and needs the locally installed Google Chrome (Mercari). Both are already true here.
- It finds its own Python (`.venv/Scripts/python.exe` inside the repo) and its own secrets
  (`.env` inside the repo). Do not read, copy, print or move `.env`.
- It needs `bash` (Git for Windows, `C:\Program Files\Git\bin\bash.exe`) on the PATH of the
  process that runs it. Hermes runs `.sh` scripts via `shutil.which("bash")`; if bash is not on
  the gateway's PATH, call it by absolute path from the wrapper instead.
- Exit code 1 from the script after "push failed after 3 attempts" is an expected rare outcome
  (GitHub Actions pushed at the same moment); the next run recovers on its own. Do not retry
  inside the job.
- Hermes's default script timeout (3600 s) is fine. Interval is exactly `30m`.

## Steps

1. In the scripts directory of the profile whose gateway is running (currently `finance`;
   `hermes gateway status` shows it), create `bag-home.sh`:

   ```sh
   #!/usr/bin/env bash
   # Runs the bag tracker's Depop/Mercari pass and syncs state with GitHub. Every 30 min.
   REPO="/c/Users/marcu/Documents/Bag search tracker/bag-tracker"
   cd "$REPO" || exit 1
   exec bash ./run_home.sh >> "$REPO/state/home.log" 2>&1
   ```

2. Create the job (no agent, no prompt):

   ```
   hermes cron create 30m --no-agent --script bag-home.sh --workdir "C:\Users\marcu\Documents\Bag search tracker\bag-tracker" --name bag-tracker-home
   ```
   Use the same profile as the running gateway (the profile flag, if the CLI needs one).

3. Trigger it once now (`hermes cron run bag-tracker-home`), wait for it to finish (up to 5 min),
   then verify all three:
   - `hermes cron runs bag-tracker-home` shows a successful run.
   - `tail -5 "<repo>/state/home.log"` ends with `nothing to send` or `sent via [...]`
     (or the push-failed line described above).
   - `git -C "<repo>" log --oneline origin/main -1` shows a commit starting `state(home):` with a
     timestamp from this run, OR the log shows the run produced no state change (rare on the
     first run; if so, trigger once more).

4. Report: the job id/name, the schedule, the run result, and the commit hash if one landed.

## Do not

- Do not change the interval (30 minutes is deliberate; more often risks a blocked IP).
- Do not run `tracker.py` yourself, and never with `--init`; do not edit anything in the repo,
  including `config.yaml`, `run_home.sh`, or `.env`.
- Do not wrap the job in a model prompt, add retries, proxies, or notifications; the script
  already emails Marcus and commits its own state.
- Do not create more than one job for this.

## Outcome (2026-09-23)

Registered as `bag-tracker-home` (every 30m, no-agent) under the `finance` profile. The `.sh` wrapper
failed from the gateway with exit 127 because the gateway's PATH has neither Git Bash nor git. Replaced
by `bag-home.py` in the same scripts folder: Hermes runs `.py` with its own interpreter, and the
wrapper launches `C:\Program Files\Gitinash.exe ./run_home.sh` with Git's directories prepended
to PATH, appending to `state/home.log`. First triggered run pushed `state(home): 2026-09-23T17:47Z`.
