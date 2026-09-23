"""Mercari, free, via a real headless browser (Playwright) from a residential IP.

Mercari's search is client-rendered and sits behind a Cloudflare challenge that plain HTTP
can't pass (verified from a cloud container: "Just a moment..."). A headless Chromium on a
home connection normally clears it. This adapter loads the search page sorted newest-first,
waits for item links, and reads title/price/image out of the DOM.

Setup once:  pip install playwright && playwright install chromium

Verified Sep 2026 from a home IP: the search page loads, but the GraphQL calls it makes to
/v1/api get a Cloudflare managed challenge whenever the browser advertises itself as automated.
Playwright's bundled Chromium fails in every mode (headless shell, new headless, headed). The
locally installed Google Chrome, launched with a dedicated persistent profile and with the
automation flag turned off, passes cleanly in headless mode, even from a cold profile. That is
what `_launch` does; if Chrome isn't installed it falls back to the bundled Chromium (which will
most likely get 0 items, and the log says so).

If it returns 0 items, run `python tracker.py --probe mercari` at home: it saves a screenshot +
HTML to state/probe/ so you can see whether it's a challenge page or just a changed selector.
"""
import re
import os

SEARCH = "https://www.mercari.com/search/?keyword={q}&sortBy=2&itemStatuses=1"  # sortBy=2 newest, status=1 on sale

_JS_EXTRACT = r"""
() => {
  const seen = new Set(); const out = [];
  for (const a of document.querySelectorAll('a[href*="/us/item/"]')) {
    const m = a.href.match(/\/us\/item\/(m\d+)/); if (!m || seen.has(m[1])) continue;
    seen.add(m[1]);
    const card = a.closest('[data-testid]') || a;
    const img = card.querySelector('img');
    const text = card.innerText || '';
    const pm = text.match(/\$\s?([\d,]+(?:\.\d{2})?)/);
    const title = (img && img.alt) || a.getAttribute('aria-label') || text.split('\n')[0] || '';
    out.push({ id: m[1], url: a.href.split('?')[0], title: title.trim(),
               price: pm ? parseFloat(pm[1].replace(/,/g,'')) : null,
               image: img ? (img.currentSrc || img.src) : null });
  }
  return out;
}
"""


UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36"
PROFILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "state", "browser-profile")


def _browser():
    from playwright.sync_api import sync_playwright
    return sync_playwright()


def _launch(p):
    """Persistent context on the locally installed Chrome; bundled Chromium as a fallback."""
    common = dict(headless=True, user_agent=UA, locale="en-US", viewport={"width": 1280, "height": 900})
    os.makedirs(PROFILE, exist_ok=True)
    try:
        return p.chromium.launch_persistent_context(
            PROFILE, channel="chrome",
            args=["--disable-blink-features=AutomationControlled"], ignore_default_args=["--enable-automation"],
            **common)
    except Exception as e:  # no Google Chrome on this machine
        print(f"[mercari] Chrome launch failed ({str(e).splitlines()[0][:80]}); falling back to bundled Chromium", flush=True)
        return p.chromium.launch_persistent_context(PROFILE, **common)


def search(query, max_price=None, limit=40, probe_dir=None):
    from urllib.parse import quote
    url = SEARCH.format(q=quote(query))
    with _browser() as p:
        ctx = _launch(p)
        b = ctx  # closing the context closes the browser
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
            page.wait_for_selector('a[href*="/us/item/"]', timeout=30000)
        except Exception:
            pass
        page.wait_for_timeout(1500)
        items = page.evaluate(_JS_EXTRACT)
        if probe_dir:
            os.makedirs(probe_dir, exist_ok=True)
            page.screenshot(path=os.path.join(probe_dir, "mercari.png"), full_page=False)
            with open(os.path.join(probe_dir, "mercari.html"), "w") as f:
                f.write(page.content())
        b.close()
    out = []
    for it in items[:limit]:
        if max_price and it.get("price") is not None and it["price"] > max_price:
            continue
        out.append({
            "source": "mercari", "id": it["id"], "title": it.get("title") or "",
            "price": it.get("price"), "currency": "USD", "url": it["url"], "image": it.get("image"),
            "condition": None, "seller": None, "created": None, "buying": "fixed",
        })
    return out
