#!/usr/bin/env python3
"""Bag tracker.

  python tracker.py --sources cloud    # eBay + Poshmark: free, work from anywhere (GitHub Actions)
  python tracker.py --sources home     # Depop + Mercari: free, but need a home (residential) IP
  python tracker.py --sources all      # everything free
  python tracker.py --sources apify    # optional paid fallback for Depop/Mercari (needs APIFY_TOKEN)
  python tracker.py --init             # record everything currently listed WITHOUT alerting (do this once)
  python tracker.py --dry-run          # show what would be sent; don't notify, don't save
  python tracker.py --probe depop|mercari|poshmark|apify:depop   # print a raw result to debug a source
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

import yaml

from sources import ebay, poshmark, depop, mercari, apify_actor
import notify

ROOT = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(ROOT, "state", "seen.json")


# ---------- matching ----------
def _norm(s):
    return re.sub(r"[^a-z0-9#& ]+", " ", (s or "").lower())


def _has(title, term):
    term = term.lower().strip()
    if term.isdigit():  # style numbers: whole-token match so "1463" doesn't match "14630"
        return re.search(rf"(?<![0-9]){re.escape(term)}(?![0-9])", title) is not None
    return term in title


def match_bag(title, bag, global_exclude):
    t = _norm(title)
    for term in global_exclude + (bag.get("exclude") or []):
        if _has(t, term):
            return False
    for group in bag["must"]:
        if not any(_has(t, term) for term in group):
            return False
    return True


def classify(listing, bags, global_exclude):
    """Return the first bag this listing matches, or None."""
    for bag in bags:
        if match_bag(listing["title"], bag, global_exclude):
            if listing.get("price") is not None and bag.get("max_price") and listing["price"] > bag["max_price"]:
                continue
            return bag
    return None


# ---------- state ----------
def load_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state, ttl_days):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=ttl_days)).isoformat()
    state = {k: v for k, v in state.items() if v.get("last_seen", "") >= cutoff}
    with open(STATE, "w") as f:
        json.dump(state, f, indent=1, sort_keys=True)
    return state


# ---------- collection ----------
def collect_ebay(cfg, bags, log):
    out = []
    for bag in bags:
        for q in bag.get("ebay_queries", []):
            try:
                res = ebay.search(q, cfg["ebay"], bag.get("max_price"))
                log(f"ebay  {len(res):3d}  {q!r}")
                out.extend(res)
            except Exception as e:
                log(f"ebay  ERR  {q!r}: {e}")
            time.sleep(0.3)
    return out


def collect_poshmark(cfg, bags, log):
    out = []
    for bag in bags:
        for q in bag.get("ebay_queries", []):
            try:
                res = poshmark.search(q, bag.get("max_price"))
                log(f"poshmark {len(res):3d}  {q!r}")
                out.extend(res)
            except Exception as e:
                log(f"poshmark ERR  {q!r}: {e}")
            time.sleep(1.0)
    return out


def _deep_queries(cfg, bags):
    qs = list(cfg.get("sweep_queries", []))
    for bag in bags:
        qs.extend(bag.get("extra_queries", []))
    seen, out = set(), []
    for q in qs:
        if q not in seen:
            seen.add(q); out.append(q)
    return out


def collect_depop(cfg, bags, log):
    out = []
    for q in _deep_queries(cfg, bags):
        try:
            res = depop.search(q, None, cfg.get("deep_limit", 24))
            log(f"depop    {len(res):3d}  {q!r}")
            out.extend(res)
        except Exception as e:
            log(f"depop    ERR  {q!r}: {e}")
        time.sleep(2.0)
    return out


def collect_mercari(cfg, bags, log):
    out = []
    for q in _deep_queries(cfg, bags):
        try:
            res = mercari.search(q, None, cfg.get("deep_limit", 24))
            log(f"mercari  {len(res):3d}  {q!r}")
            out.extend(res)
        except Exception as e:
            log(f"mercari  ERR  {q!r}: {e}")
        time.sleep(2.0)
    return out


def collect_apify(cfg, bags, log):
    out = []
    acfg = cfg["apify"]
    queries = _deep_queries(cfg, bags)
    seen_q = set()
    for platform in acfg.get("platforms", []):
        for q in queries:
            if (platform, q) in seen_q:
                continue
            seen_q.add((platform, q))
            try:
                res = apify_actor.search(platform, q, acfg)
                log(f"{platform:<8}{len(res):3d}  {q!r}")
                out.extend(res)
            except Exception as e:
                log(f"{platform:<8}ERR  {q!r}: {e}")
    return out


# ---------- main ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default="cloud",
                    choices=["ebay", "poshmark", "depop", "mercari", "apify", "cloud", "home", "all"])
    ap.add_argument("--init", action="store_true", help="seed state without alerting")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--probe", metavar="SOURCE", help="poshmark | depop | mercari | apify:<platform>: print a raw result and exit")
    args = ap.parse_args()

    with open(os.path.join(ROOT, "config.yaml")) as f:
        cfg = yaml.safe_load(f)
    bags = cfg["bags"]
    gex = cfg.get("global_exclude", [])
    log = lambda s: print(s, flush=True)

    if args.probe:
        q = "coach signature"
        if args.probe.startswith("apify:"):
            rec = apify_actor.probe(args.probe.split(":", 1)[1], q, cfg["apify"])
        elif args.probe == "poshmark":
            rec = poshmark.search(q)[:2]
        elif args.probe == "depop":
            rec = depop.raw(q, 3, probe_dir=os.path.join(ROOT, "state", "probe"))
            print("screenshot + html saved to state/probe/")
        elif args.probe == "mercari":
            rec = mercari.search(q, None, 5, probe_dir=os.path.join(ROOT, "state", "probe"))
            print("screenshot + html saved to state/probe/")
        else:
            sys.exit("unknown probe target")
        print(json.dumps(rec, indent=2)[:6000])
        return

    groups = {
        "ebay": ["ebay"], "poshmark": ["poshmark"], "depop": ["depop"], "mercari": ["mercari"], "apify": ["apify"],
        "cloud": ["ebay", "poshmark"], "home": ["depop", "mercari"], "all": ["ebay", "poshmark", "depop", "mercari"],
    }[args.sources]
    collectors = {"ebay": collect_ebay, "poshmark": collect_poshmark, "depop": collect_depop,
                  "mercari": collect_mercari, "apify": collect_apify}
    listings = []
    for g in groups:
        listings += collectors[g](cfg, bags, log)

    # dedupe across queries
    uniq = {}
    for l in listings:
        if l.get("id") and l.get("url"):
            uniq[f"{l['source']}:{l['id']}"] = l
    log(f"{len(uniq)} unique listings fetched")

    state = load_state()
    now = datetime.now(timezone.utc).isoformat()
    alerts = []
    matched = 0
    for key, l in uniq.items():
        bag = classify(l, bags, gex)
        if not bag:
            continue
        matched += 1
        prev = state.get(key)
        price = l.get("price")
        base = {**l, "bag": bag["name"], "bag_id": bag["id"]}
        if prev is None:
            kind = "deal" if (price is not None and bag.get("deal_price") and price <= bag["deal_price"]) else "new"
            alerts.append({**base, "kind": kind})
            state[key] = {"bag": bag["id"], "price": price, "first_seen": now, "last_seen": now, "title": l["title"]}
        else:
            old = prev.get("price")
            frac = cfg.get("price_drop_fraction", 0.15)
            if price is not None and old and price <= old * (1 - frac):
                kind = "deal" if (bag.get("deal_price") and price <= bag["deal_price"]) else "drop"
                alerts.append({**base, "kind": kind, "old_price": old})
                prev["price"] = price
            prev["last_seen"] = now

    log(f"{matched} matched a bag, {len(alerts)} alerts")

    if args.init:
        log("init: recorded current listings, no alerts sent")
        save_state(state, cfg.get("seen_ttl_days", 90))
        return

    # Loud first, then newest.
    alerts.sort(key=lambda a: ({"deal": 0, "drop": 1, "new": 2}[a["kind"]], a.get("created") or ""), reverse=False)
    for a in alerts:
        log(f"  [{a['kind']:<4}] {a['bag']:<45} ${a['price'] or 0:>6.0f}  {a['source']:<9} {a['title'][:70]}")

    if args.dry_run:
        log("dry run: nothing sent, state not saved")
        return

    sent = notify.send(alerts)
    if alerts and not sent:
        log("WARNING: alerts found but no notification channel is configured; state NOT saved so they resend next run")
        sys.exit(2)
    save_state(state, cfg.get("seen_ttl_days", 90))
    log(f"sent via {sent}" if sent else "nothing to send")


if __name__ == "__main__":
    main()
