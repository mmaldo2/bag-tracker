#!/usr/bin/env python3
"""Pull her verdicts from the Worker into state/verdicts.json and docs/verdicts.json.

Runs before tracker.py in both runners. Never fails the run: missing env vars or a dead
Worker leave the previous files in place and exit 0.
"""
import os
import sys
from datetime import datetime, timezone

import requests

import verdicts as verdicts_mod

ROOT = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(ROOT, "state", "verdicts.json")
SITE_PATH = os.path.join(ROOT, "docs", "verdicts.json")


def main():
    url, token = os.environ.get("VERDICT_URL"), os.environ.get("VERDICT_TOKEN")
    if not url or not token:
        print("verdicts: VERDICT_URL / VERDICT_TOKEN not set, skipping", flush=True)
        return 0
    try:
        r = requests.get(url.rstrip("/") + "/v", headers={"Authorization": f"Bearer {token}"}, timeout=30)
        r.raise_for_status()
        fetched = r.json()
    except Exception as e:
        print(f"verdicts: fetch failed, keeping previous file: {e}", flush=True)
        return 0
    existing = verdicts_mod.load(STATE_PATH)
    merged = verdicts_mod.merge(existing, fetched, datetime.now(timezone.utc).isoformat())
    verdicts_mod.save(merged, STATE_PATH, SITE_PATH)
    print(f"verdicts: {len(merged['listings'])} listing verdicts, {len(merged['bags'])} bag statuses", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
