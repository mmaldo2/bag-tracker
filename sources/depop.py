"""Depop, free, via a headless browser (Playwright) from a residential IP.

Depop's web API (webapi.depop.com) now answers 403 "Forbidden" to plain HTTP even from a home
connection (verified Sep 2026: its WAF rejects non-browser TLS/headers, no Cloudflare challenge
involved). The search page itself renders fine in headless Chromium from home as long as a normal
User-Agent is set, and the product cards are server-rendered into the DOM, so this adapter loads
the search page and reads slug / price / image straight out of the cards. No login, no proxy.

Setup once:  pip install playwright && playwright install chromium

Notes on what the DOM gives us (and doesn't):
  - No listing title. Each card links to /products/<username>-<title-words>-<4hex>/ and carries an
    aria-label Depop generates from the seller's attributes ("Coach women's black bag"). We build
    the title from the slug words and append the aria-label so colour/category terms can match.
  - No numeric id. The slug is stable per listing, so it is the id.
  - Discounted items show two prices; the lower one is the current price.
  - The web search has no "newest first" sort (only relevance / price), so results are relevance
    order. Dedupe against state makes that fine for alerting.
  - No sold filter; cards marked "Sold" are skipped.

`python tracker.py --probe depop` prints the raw cards and saves a screenshot + HTML to
state/probe/ so a changed selector is a one-line fix.
"""
import os
import re
from urllib.parse import quote

SEARCH = "https://www.depop.com/search/?q={q}"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"

_JS_EXTRACT = r"""
() => {
  const seen = new Set(); const out = [];
  for (const a of document.querySelectorAll('a[href*="/products/"]')) {
    const m = (a.getAttribute('href') || '').match(/\/products\/([^\/?#]+)/);
    if (!m || seen.has(m[1])) continue;
    seen.add(m[1]);
    const card = a.closest('[class*="productCardRoot"]') || a.parentElement || a;
    const img = card.querySelector('img[class*="mainImage"]') || card.querySelector('img');
    const text = card.innerText || '';
    const prices = [...text.matchAll(/\$\s?([\d,]+(?:\.\d{2})?)/g)].map(x => parseFloat(x[1].replace(/,/g, '')));
    out.push({ slug: m[1],
               alt: (a.getAttribute('aria-label') || (img && img.alt) || '').trim(),
               prices, sold: /\bsold\b/i.test(text),
               image: img ? (img.currentSrc || img.src) : null });
  }
  return out;
}
"""


def _browser():
    from playwright.sync_api import sync_playwright
    return sync_playwright()


def raw(query, limit=24, probe_dir=None):
    """Load the search page and return the raw cards as extracted from the DOM."""
    url = SEARCH.format(q=quote(query))
    with _browser() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(user_agent=UA, locale="en-US", viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_selector('a[href*="/products/"]', timeout=30000)
        except Exception:
            pass
        page.wait_for_timeout(1500)
        title = page.title()
        cards = page.evaluate(_JS_EXTRACT)
        if probe_dir:
            os.makedirs(probe_dir, exist_ok=True)
            page.screenshot(path=os.path.join(probe_dir, "depop.png"), full_page=False)
            with open(os.path.join(probe_dir, "depop.html"), "w", encoding="utf-8") as f:
                f.write(page.content())
        b.close()
    if not cards and re.search(r"forbidden|just a moment", title, re.I):
        raise RuntimeError(f"depop: blocked ({title!r}) — needs a residential IP and a browser-like User-Agent")
    return cards[:limit]


def _title_from(slug, alt):
    words = re.sub(r"^[a-z0-9_.]+-", "", slug)          # drop the leading username
    words = re.sub(r"-[0-9a-f]{4}$", "", words)          # drop the trailing hash
    title = words.replace("-", " ").strip()
    if alt and alt.lower() not in title.lower():
        title = f"{title} ({alt})" if title else alt
    return title


def search(query, max_price=None, limit=24, probe_dir=None):
    out = []
    for c in raw(query, limit, probe_dir=probe_dir):
        if c.get("sold"):
            continue
        prices = [p for p in (c.get("prices") or []) if p is not None]
        price = min(prices) if prices else None
        if max_price and price is not None and price > max_price:
            continue
        slug = c["slug"]
        out.append({
            "source": "depop",
            "id": slug,
            "title": _title_from(slug, c.get("alt") or ""),
            "price": price,
            "currency": "USD",
            "url": f"https://www.depop.com/products/{slug}/",
            "image": c.get("image"),
            "condition": None,
            "seller": slug.split("-")[0] or None,
            "created": None,
            "buying": "fixed",
        })
    return out
