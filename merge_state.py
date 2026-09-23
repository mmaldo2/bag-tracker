#!/usr/bin/env python3
"""Git merge driver for the tracker's JSON state files: union both sides instead of conflicting.

Registered per run with:  git config merge.jsonstate.driver "python merge_state.py %O %A %B"
and .gitattributes lines:  state/seen.json merge=jsonstate  (etc.)

Rules:
  seen.json          dict keyed by listing key -> union; when both sides have a key, the entry with
                     the newer last_seen wins, except first_seen keeps the older value.
  verdicts.json      {"fetched","listings","bags"} -> listings/bags union by key, newer "t" wins,
                     "notified" is true if either side says true for the same "v"; fetched = max.
  finds.json         {"generated","bags","finds"} -> finds union by "key", newer last_seen wins but
                     first_seen keeps the older; generated = max; bags = the side with the newer generated.
Any parse failure falls back to keeping "ours" (%A) and exits 0 so the rebase never wedges.
"""
import json
import sys


def _load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _newer(a, b, field):
    return a if (a.get(field) or "") >= (b.get(field) or "") else b


def merge_seen(ours, theirs):
    out = dict(theirs)
    for k, v in ours.items():
        if k in out and isinstance(v, dict) and isinstance(out[k], dict):
            w = dict(_newer(v, out[k], "last_seen"))
            w["first_seen"] = min(v.get("first_seen") or w.get("first_seen") or "", out[k].get("first_seen") or w.get("first_seen") or "") or w.get("first_seen")
            out[k] = w
        else:
            out[k] = v
    return out


def merge_verdicts(ours, theirs):
    def union(a, b, tkey):
        out = dict(b)
        for k, v in a.items():
            o = out.get(k)
            if isinstance(v, dict) and isinstance(o, dict):
                w = dict(_newer(v, o, tkey))
                if v.get("v") == o.get("v"):
                    w["notified"] = bool(v.get("notified")) or bool(o.get("notified"))
                out[k] = w
            else:
                out[k] = v
        return out
    return {
        "fetched": max(ours.get("fetched") or "", theirs.get("fetched") or "") or None,
        "listings": union(ours.get("listings") or {}, theirs.get("listings") or {}, "t"),
        "bags": union(ours.get("bags") or {}, theirs.get("bags") or {}, "t"),
    }


def merge_finds(ours, theirs):
    newer = _newer(ours, theirs, "generated")
    by_key = {}
    for rec in (theirs.get("finds") or []) + (ours.get("finds") or []):
        k = rec.get("key")
        if not k:
            continue
        if k in by_key:
            old = by_key[k]
            w = dict(_newer(rec, old, "last_seen"))
            w["first_seen"] = min(rec.get("first_seen") or "", old.get("first_seen") or "") or w.get("first_seen")
            by_key[k] = w
        else:
            by_key[k] = rec
    finds = sorted(by_key.values(), key=lambda r: r.get("first_seen") or "", reverse=True)[:40]
    return {"generated": newer.get("generated"), "bags": newer.get("bags") or {}, "finds": finds}


def main(base_path, ours_path, theirs_path):
    try:
        ours, theirs = _load(ours_path), _load(theirs_path)
        if isinstance(ours, dict) and "finds" in ours:
            merged, indent = merge_finds(ours, theirs), 1
        elif isinstance(ours, dict) and "listings" in ours:
            merged, indent = merge_verdicts(ours, theirs), 1
        else:
            merged, indent = merge_seen(ours, theirs), 1
        with open(ours_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(merged, f, indent=indent, sort_keys=("finds" not in merged))
    except Exception as e:  # never wedge a rebase over a state file
        print(f"merge_state: fell back to ours for {ours_path}: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:4]))
