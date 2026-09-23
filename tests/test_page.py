"""Drives docs/index.html in headless Chromium at phone width against a fixture finds.json.
Asserts swipes post the right verdicts and that the overlay hides swiped cards after reload."""
import json
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = {
    "generated": "2026-09-23T02:00:00+00:00",
    "bags": {"chelsea-braided": {"name": "Chelsea", "deal_price": 120},
             "patchwork-leopard-tote": {"name": "Patchwork", "deal_price": 110}},
    "finds": [
        {"key": "mercari:m1", "bag": "chelsea-braided", "title": "Chelsea one", "price": 190, "old_price": None,
         "currency": "USD", "source": "mercari", "url": "https://example.com/1", "image": "img/chelsea-braided.jpg",
         "seller": None, "condition": None, "first_seen": "2026-09-23T01:00:00+00:00",
         "last_seen": "2026-09-23T02:00:00+00:00", "kind": "new", "stale": False},
        {"key": "depop:d2", "bag": "patchwork-leopard-tote", "title": "Patchwork two", "price": 40, "old_price": None,
         "currency": "USD", "source": "depop", "url": "https://example.com/2", "image": "img/patchwork-leopard-tote.jpg",
         "seller": "x", "condition": None, "first_seen": "2026-09-22T01:00:00+00:00",
         "last_seen": "2026-09-23T02:00:00+00:00", "kind": "deal", "stale": False},
        {"key": "ebay:e3", "bag": "patchwork-leopard-tote", "title": "Patchwork three", "price": 150, "old_price": 199,
         "currency": "USD", "source": "ebay", "url": "https://example.com/3", "image": "img/patchwork-leopard-tote.jpg",
         "seller": None, "condition": "Pre-owned", "first_seen": "2026-09-18T01:00:00+00:00",
         "last_seen": "2026-09-19T02:00:00+00:00", "kind": "drop", "stale": True},
    ],
}


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    d = tmp_path_factory.mktemp("site")
    shutil.copytree(ROOT / "docs", d, dirs_exist_ok=True)
    (d / "finds.json").write_text(json.dumps(FIXTURE), encoding="utf-8")
    (d / "verdicts.json").write_text(json.dumps({"fetched": "2026-09-23T02:00:00+00:00", "listings": {}, "bags": {}}), encoding="utf-8")
    port = _free_port()
    proc = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"], cwd=d,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.0)
    yield f"http://127.0.0.1:{port}/"
    proc.kill()
    proc.wait()


@pytest.fixture
def page(site):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, has_touch=True, is_mobile=True)
        pg = ctx.new_page()
        posts = []
        pg.add_init_script("window.WORKER_URL_OVERRIDE = 'https://worker.test'")
        def handle(route):
            posts.append(json.loads(route.request.post_data or "{}"))
            route.fulfill(status=204, headers={"Access-Control-Allow-Origin": "*"})
        pg.route("https://worker.test/v", handle)
        pg.posts = posts
        pg.goto(site)
        pg.wait_for_selector(".card")
        yield pg
        browser.close()


def _drag_top_card(pg, dx):
    card = pg.locator(".card:not(.next)")
    box = card.bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    pg.mouse.move(x, y)
    pg.mouse.down()
    for i in range(1, 11):
        pg.mouse.move(x + dx * i / 10, y)
    pg.mouse.up()


def _wait_for_posts(pg, n):
    """Bounded poll: the POST is captured by a Python route handler, so give it a moment
    to land rather than asserting on page.posts immediately after an action."""
    for _ in range(20):
        if len(pg.posts) >= n:
            return
        pg.wait_for_timeout(100)
    pytest.fail(f"no POST arrived (have {len(pg.posts)}, wanted {n})")


def test_initial_render(page):
    assert page.locator("#badge").inner_text() == "3"
    assert "Chelsea one" in page.locator(".card:not(.next) h3").inner_text()
    assert page.locator(".card:not(.next) .ref").count() == 1
    assert "Last checked" in page.locator("#subline").inner_text()


def test_swipe_left_posts_no_and_advances(page):
    _drag_top_card(page, -260)
    page.wait_for_function("document.querySelector('.card:not(.next) h3').textContent.includes('Patchwork two')")
    _wait_for_posts(page, 1)
    assert page.posts[-1] == {"token": page.posts[-1]["token"], "kind": "listing", "key": "mercari:m1", "value": "no"}
    assert page.locator("#badge").inner_text() == "2"


def test_button_keep_posts_keep_and_shows_in_kept(page):
    page.click("#btn-keep")
    page.wait_for_function("document.querySelector('.card:not(.next) h3').textContent.includes('Patchwork two')")
    _wait_for_posts(page, 1)
    assert page.posts[-1]["kind"] == "listing" and page.posts[-1]["value"] == "keep" and page.posts[-1]["key"] == "mercari:m1"
    page.click(".tabs button[data-tab=kept]")
    assert "Chelsea one" in page.locator("#kept").inner_text()
    page.click("#kept .x")
    _wait_for_posts(page, 2)
    assert page.posts[-1] == {**page.posts[-1], "key": "mercari:m1", "value": "no"}


def test_undo_restores_card_and_posts_clear(page):
    page.click("#btn-no")
    page.wait_for_function("document.querySelector('.card:not(.next) h3').textContent.includes('Patchwork two')")
    page.click("#undo")
    page.wait_for_function("document.querySelector('.card:not(.next) h3').textContent.includes('Chelsea one')")
    _wait_for_posts(page, 2)
    assert page.posts[-1]["value"] == "clear" and page.posts[-1]["key"] == "mercari:m1"


def test_overlay_survives_reload(page):
    page.click("#btn-no")
    page.wait_for_function("document.querySelector('.card:not(.next) h3').textContent.includes('Patchwork two')")
    page.reload()
    page.wait_for_selector(".card")
    assert "Patchwork two" in page.locator(".card:not(.next) h3").inner_text()
    assert page.locator("#badge").inner_text() == "2"


def test_bag_status_posts(page):
    page.click(".tabs button[data-tab=bags]")
    page.click('.bag:has-text("Chelsea Optic") .seg button[data-s=owned]')
    _wait_for_posts(page, 1)
    assert page.posts[-1] == {**page.posts[-1], "kind": "bag", "key": "chelsea-braided", "value": "owned"}
    assert page.locator('.bag:has-text("Chelsea Optic") .owned-note').count() == 1


def test_empty_state_when_all_reviewed(page):
    for _ in range(3):
        page.click("#btn-no")
        page.wait_for_timeout(350)
    assert "Nothing new to review" in page.locator("#review-empty").inner_text()
    assert page.locator("#badge").inner_text() == ""


def test_missing_finds_file(site):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pg = browser.new_page(viewport={"width": 390, "height": 844})
        pg.route("**/finds.json", lambda r: r.fulfill(status=404))
        pg.goto(site)
        pg.wait_for_selector("#review-empty:not([hidden])")
        assert "hasn" in pg.locator("#review-empty").inner_text() and "run yet" in pg.locator("#review-empty").inner_text()
        browser.close()


def test_no_horizontal_overflow(page):
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
