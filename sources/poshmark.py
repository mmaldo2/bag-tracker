"""Poshmark, free. Plain HTTP: the search page embeds window.__INITIAL_STATE__ with up to 48 listings.
Works from datacenter IPs (GitHub Actions) as of Sep 2026. No login, no proxy.
"""
import json
import time
import requests

H = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}
COND = {"nwt": "New with tags", "uf": "Used", "ret": "Retail", "closet": "Used"}


def _state(html):
    i = html.find("__INITIAL_STATE__")
    if i < 0:
        return None
    j = html.find("{", i)
    obj, _ = json.JSONDecoder().raw_decode(html[j:])
    return obj


def search(query, max_price=None, retries=2):
    url = "https://poshmark.com/search"
    params = {"query": query, "department": "Women", "sort_by": "added_desc", "availability": "available"}
    if max_price:
        params["price"] = f"0-{int(max_price)}"
    last = None
    for attempt in range(retries + 1):
        r = requests.get(url, params=params, headers=H, timeout=30)
        state = _state(r.text) if r.status_code == 200 else None
        if state:
            break
        last = r.status_code
        time.sleep(3 * (attempt + 1))
    else:
        raise RuntimeError(f"poshmark: no state in page (status {last})")
    items = (((state.get("$_search") or {}).get("gridData") or {}).get("data")) or []
    out = []
    for it in items:
        inv = it.get("inventory") or {}
        if inv.get("status") not in (None, "available"):
            continue
        pa = it.get("price_amount") or {}
        try:
            price = float(pa.get("val"))
        except (TypeError, ValueError):
            price = None
        cover = it.get("cover_shot") or {}
        out.append({
            "source": "poshmark",
            "id": it.get("id"),
            "title": it.get("title", "") or "",
            "price": price,
            "currency": pa.get("currency_code", "USD"),
            "url": f"https://poshmark.com/listing/{it.get('id')}",
            "image": cover.get("url") or it.get("picture_url"),
            "condition": COND.get(it.get("condition"), it.get("condition")),
            "seller": it.get("creator_username"),
            "created": it.get("created_at"),
            "buying": "fixed",
        })
    return out
