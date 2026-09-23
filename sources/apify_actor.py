"""Poshmark / Mercari / Depop via the Apify actor crawlerbros/mercari-poshmark-depop-scraper.

Needs APIFY_TOKEN.  Pay-per-result (about $3 per 1,000 listings at time of writing), so the
number of queries, max_items and how often the Apify cycle runs are the cost knobs.

Input (searchListings mode):  platform, mode, query, sortBy, maxItems, minPrice, maxPrice
Output records:               platform, id, title, url, price, currency, coverImageUrl,
                              condition, status, createdAt, seller{username}, recordType
"""
import os
import time
import requests

API = "https://api.apify.com/v2"


def _tok():
    t = os.environ.get("APIFY_TOKEN")
    if not t:
        raise RuntimeError("APIFY_TOKEN not set")
    return t


def run_actor(actor, run_input, poll_seconds=15, max_wait=900):
    """Start an actor run, wait for it to finish, return the dataset items."""
    r = requests.post(f"{API}/acts/{actor}/runs", params={"token": _tok()}, json=run_input, timeout=60)
    r.raise_for_status()
    run = r.json()["data"]
    run_id, ds_id = run["id"], run["defaultDatasetId"]
    waited = 0
    status = run.get("status")
    while status in ("READY", "RUNNING") and waited < max_wait:
        time.sleep(poll_seconds)
        waited += poll_seconds
        s = requests.get(f"{API}/actor-runs/{run_id}", params={"token": _tok()}, timeout=30)
        s.raise_for_status()
        status = s.json()["data"]["status"]
    if status != "SUCCEEDED":
        # Abort a hung run so it stops billing, then report.
        if status in ("READY", "RUNNING"):
            requests.post(f"{API}/actor-runs/{run_id}/abort", params={"token": _tok()}, timeout=30)
        raise RuntimeError(f"Apify run {run_id} ended with status {status}")
    d = requests.get(f"{API}/datasets/{ds_id}/items", params={"token": _tok(), "clean": "true"}, timeout=60)
    d.raise_for_status()
    return d.json()


def normalize(rec):
    if rec.get("recordType") not in (None, "listing"):
        return None
    if rec.get("status") in ("sold", "sold_out"):
        return None
    try:
        price = float(rec.get("price")) if rec.get("price") is not None else None
    except (TypeError, ValueError):
        price = None
    seller = rec.get("seller") or {}
    return {
        "source": rec.get("platform", "apify"),
        "id": str(rec.get("id") or rec.get("url")),
        "title": rec.get("title", "") or "",
        "price": price,
        "currency": rec.get("currency", "USD"),
        "url": rec.get("url"),
        "image": rec.get("coverImageUrl") or ((rec.get("imageUrls") or [None])[0]),
        "condition": rec.get("condition"),
        "seller": seller.get("username") if isinstance(seller, dict) else None,
        "created": rec.get("createdAt"),
        "buying": "fixed",
    }


def search(platform, query, cfg, max_price=None):
    run_input = {
        "platform": platform,
        "mode": "searchListings",
        "query": query,
        "maxItems": int(cfg.get("max_items", 15)),
    }
    if cfg.get("sort_by"):
        run_input["sortBy"] = cfg["sort_by"]
    if max_price:
        run_input["maxPrice"] = int(max_price)
    if platform == "poshmark":
        run_input["availableOnly"] = True
    if platform == "mercari":
        run_input["itemStatus"] = "on_sale"
    items = run_actor(cfg["actor"], run_input, cfg.get("poll_seconds", 15), cfg.get("max_wait_seconds", 900))
    out = []
    for rec in items:
        n = normalize(rec)
        if n:
            out.append(n)
    return out


def probe(platform, query, cfg):
    """Run one small query and return the raw first record, for checking field names."""
    cfg = dict(cfg, max_items=3)
    run_input = {"platform": platform, "mode": "searchListings", "query": query, "maxItems": 3}
    items = run_actor(cfg["actor"], run_input, cfg.get("poll_seconds", 15), cfg.get("max_wait_seconds", 900))
    return items[0] if items else None
