"""eBay Browse API source (official, free, app-token auth).

Needs EBAY_CLIENT_ID and EBAY_CLIENT_SECRET from a keyset at developer.ebay.com.
"""
import base64
import os
import time
import requests

TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
SCOPE = "https://api.ebay.com/oauth/api_scope"

_token = {"value": None, "expires": 0}


def _get_token():
    if _token["value"] and time.time() < _token["expires"] - 60:
        return _token["value"]
    cid, secret = os.environ.get("EBAY_CLIENT_ID"), os.environ.get("EBAY_CLIENT_SECRET")
    if not cid or not secret:
        raise RuntimeError("EBAY_CLIENT_ID / EBAY_CLIENT_SECRET not set")
    basic = base64.b64encode(f"{cid}:{secret}".encode()).decode()
    r = requests.post(
        TOKEN_URL,
        headers={"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "client_credentials", "scope": SCOPE},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    _token["value"] = data["access_token"]
    _token["expires"] = time.time() + int(data.get("expires_in", 7200))
    return _token["value"]


def search(query, cfg, max_price=None):
    """Return a list of normalized listings for one query, newest first."""
    filters = [cfg.get("extra_filters", "priceCurrency:USD")]
    if max_price:
        filters.insert(0, f"price:[..{int(max_price)}]")
    params = {
        "q": query,
        "sort": "newlyListed",
        "limit": int(cfg.get("limit", 50)),
        "filter": ",".join(f for f in filters if f),
    }
    headers = {
        "Authorization": f"Bearer {_get_token()}",
        "X-EBAY-C-MARKETPLACE-ID": cfg.get("marketplace", "EBAY_US"),
    }
    r = requests.get(SEARCH_URL, params=params, headers=headers, timeout=30)
    if r.status_code == 401:  # token went stale mid-run
        _token["value"] = None
        headers["Authorization"] = f"Bearer {_get_token()}"
        r = requests.get(SEARCH_URL, params=params, headers=headers, timeout=30)
    r.raise_for_status()
    out = []
    for it in r.json().get("itemSummaries", []):
        price = it.get("price") or {}
        try:
            value = float(price.get("value"))
        except (TypeError, ValueError):
            value = None
        out.append({
            "source": "ebay",
            "id": it.get("itemId"),
            "title": it.get("title", ""),
            "price": value,
            "currency": price.get("currency", "USD"),
            "url": it.get("itemWebUrl"),
            "image": (it.get("image") or {}).get("imageUrl"),
            "condition": it.get("condition"),
            "seller": (it.get("seller") or {}).get("username"),
            "created": it.get("itemCreationDate"),
            "buying": ",".join(it.get("buyingOptions", [])),
        })
    return out
