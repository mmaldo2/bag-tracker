"""Her verdicts, pulled from the Worker by sync_verdicts.py.

File shape (state/verdicts.json and docs/verdicts.json are identical):
  {"fetched": iso,
   "listings": {"<source>:<id>": {"v": "no"|"keep", "t": iso, "notified": bool}},
   "bags":     {"<bag id>":       {"status": "wanted"|"found"|"owned", "t": iso}}}

`notified` is ours (set by tracker.py once a keep has been mentioned in a notification);
everything else is what the Worker returned. Unknown keys are ignored by the tracker, never
deleted here.
"""
import json
import os

LISTING_VALUES = ("no", "keep")
BAG_VALUES = ("wanted", "found", "owned")


def _empty():
    return {"fetched": None, "listings": {}, "bags": {}}


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return _empty()
    if not isinstance(d, dict):
        return _empty()
    for k in ("listings", "bags"):
        if d.get(k) is not None and not isinstance(d.get(k), dict):
            return _empty()
    return {"fetched": d.get("fetched"),
            "listings": dict(d.get("listings") or {}),
            "bags": dict(d.get("bags") or {})}


def save(verdicts, *paths):
    for p in paths:
        p = str(p)
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            json.dump(verdicts, f, indent=1, sort_keys=True)


def merge(existing, fetched, now_iso):
    """Take the Worker's payload as truth, carry `notified` over where the verdict is unchanged."""
    listings = {}
    for k, v in (fetched.get("listings") or {}).items():
        if not isinstance(v, dict) or v.get("v") not in LISTING_VALUES:
            continue
        old = existing["listings"].get(k) or {}
        listings[k] = {"v": v["v"], "t": v.get("t"),
                       "notified": bool(old.get("notified")) and old.get("v") == v["v"]}
    bags = {}
    for b, v in (fetched.get("bags") or {}).items():
        if isinstance(v, dict) and v.get("status") in BAG_VALUES:
            bags[b] = {"status": v["status"], "t": v.get("t")}
    return {"fetched": now_iso, "listings": listings, "bags": bags}


def owned_bags(verdicts):
    return {b for b, v in verdicts["bags"].items() if isinstance(v, dict) and v.get("status") == "owned"}


def rejected(verdicts):
    return {k for k, v in verdicts["listings"].items() if isinstance(v, dict) and v.get("v") == "no"}


def unnotified_keeps(verdicts):
    return [k for k, v in verdicts["listings"].items()
            if isinstance(v, dict) and v.get("v") == "keep" and not v.get("notified")]


def mark_notified(verdicts, keys):
    for k in keys:
        if k in verdicts["listings"]:
            verdicts["listings"][k]["notified"] = True
