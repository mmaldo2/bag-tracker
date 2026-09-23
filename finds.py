"""docs/finds.json: the listings the page shows. Rules live in notes/specs/2026-09-23-finds-review-design.md.

Record shape:
  {"key", "bag", "title", "price", "old_price", "currency", "source", "url", "image", "seller",
   "condition", "first_seen", "last_seen", "kind": "new"|"deal"|"drop", "stale": bool}
"""
import json
import os
from datetime import datetime, timedelta

MAX = 40
KEEP_DAYS = 14
STALE_DAYS = 3


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return list(d.get("finds") or [])
    except (FileNotFoundError, json.JSONDecodeError, OSError, AttributeError):
        return []


def _parse(s):
    try:
        return datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def update(existing, matched, rejected, now):
    """Merge this run's matches into the existing records, then apply the prune/stale/cap rules."""
    now_iso = now.isoformat()
    by_key = {r["key"]: dict(r) for r in existing if r.get("key")}
    for m in matched:
        l = m["listing"]
        rec = by_key.get(m["key"]) or {"key": m["key"], "first_seen": m.get("first_seen") or now_iso,
                                       "kind": "new", "old_price": None}
        rec.update({
            "bag": m["bag"],
            "title": l.get("title") or "",
            "price": l.get("price"),
            "currency": l.get("currency") or "USD",
            "source": l["source"],
            "url": l.get("url"),
            "image": l.get("image"),
            "seller": l.get("seller"),
            "condition": l.get("condition"),
            "last_seen": now_iso,
        })
        if m.get("kind"):
            rec["kind"] = m["kind"]
            if m["kind"] in ("drop", "deal") and m.get("old_price") is not None:
                rec["old_price"] = m["old_price"]
        by_key[m["key"]] = rec

    cutoff = now - timedelta(days=KEEP_DAYS)
    stale_cutoff = now - timedelta(days=STALE_DAYS)
    out = []
    for rec in by_key.values():
        if rec["key"] in rejected:
            continue
        first = _parse(rec.get("first_seen"))
        if first is None or first < cutoff:
            continue
        last = _parse(rec.get("last_seen"))
        rec["stale"] = bool(last is None or last < stale_cutoff)
        out.append(rec)
    out.sort(key=lambda r: r.get("first_seen") or "", reverse=True)
    return out[:MAX]


def save(path, finds, bags_cfg, now):
    doc = {
        "generated": now.isoformat(),
        "bags": {b["id"]: {"name": b["name"], "deal_price": b.get("deal_price")} for b in bags_cfg},
        "finds": finds,
    }
    path = str(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(doc, f, indent=1)
