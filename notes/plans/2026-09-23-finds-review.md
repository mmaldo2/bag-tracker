# Finds Review Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the static slideshow with a phone-first review page fed by the tracker, whose swipe verdicts flow back through a free Cloudflare Worker so rejected listings never re-alert and owned bags stop being searched.

**Architecture:** The tracker gains two pure modules (`finds.py`, `verdicts.py`) and writes `docs/finds.json`; a tiny `sync_verdicts.py` pulls verdicts from the Worker before each run. `docs/index.html` (vanilla JS, one file) reads both JSON files from its own GitHub Pages origin and POSTs each swipe to the Worker. The Worker is ~80 lines on KV.

**Tech Stack:** Python 3.14 in `.venv` (requests, pyyaml, playwright, pytest), Cloudflare Workers + KV via `npx wrangler` (Node 24 is installed), GitHub Pages from `/docs` on `main`, vanilla HTML/CSS/JS.

**Spec:** `notes/specs/2026-09-23-finds-review-design.md`

## Global Constraints

- Nothing costs money: Cloudflare free tier, GitHub free plan (public repo), no Apify, no proxies.
- Do not increase request cadence or reduce sleeps in `tracker.py`.
- Matching rules only tighten; no changes to `match_bag`/`classify` logic.
- `.env` is never committed. Secrets go in Actions secrets and `.env` only. `worker/.dev.vars` is also ignored.
- The page is one HTML file plus JSON (and an `img/` folder); no build step, no framework.
- Repo root is `bag-tracker/`. All paths below are relative to it. Python is `.venv/Scripts/python` (Windows). Commit with `git -c user.name=marcus -c user.email=marcusmaldonado15@gmail.com commit ...` unless git identity has been configured.
- Line endings are LF (`.gitattributes` enforces it).
- Bag ids everywhere are the ids in `config.yaml`: `black-flap-1463`, `black-soho-satchel`, `black-soho-flap-shoulder`, `brown-large-soho-flap`, `bonnie-satchel`, `chelsea-braided`, `brown-soho-satchel`, `patchwork-leopard-tote`, `poppy-pink-double-pocket`.

## File Structure

| Path | Responsibility |
|---|---|
| `verdicts.py` (new) | Load/save/merge verdict files; pure helpers: owned bags, rejected keys, unnotified keeps, mark notified. |
| `finds.py` (new) | Load/update/save `docs/finds.json`; prune, stale, cap, sort rules. |
| `sync_verdicts.py` (new) | CLI: GET Worker -> merge -> write `state/verdicts.json` + `docs/verdicts.json`. Never fails the run. |
| `tracker.py` (modify) | Wire verdicts (owned skip, rejected skip), finds writing, kept notifications. |
| `notify.py` (modify) | `send(alerts, kept)`; "She kept" in every channel. |
| `run_home.sh`, `.github/workflows/track.yml` (modify) | Run sync first; commit the four state files. |
| `worker/wrangler.toml`, `worker/src/index.js` (new) | Verdict store API. |
| `docs/index.html`, `docs/img/*.jpg` (new) | The page. |
| `tests/test_verdicts.py`, `tests/test_finds.py`, `tests/test_notify.py`, `tests/test_page.py` (new) | pytest. |
| `README.md` (modify) | Document the page, Worker, secrets. |

---

### Task 1: `verdicts.py`

**Files:**
- Create: `verdicts.py`
- Test: `tests/test_verdicts.py`

**Interfaces:**
- Produces:
  - `load(path) -> dict` with keys `fetched`, `listings`, `bags` (empty dict shape on missing/invalid file).
  - `save(verdicts, *paths) -> None`
  - `merge(existing, fetched, now_iso) -> dict` (fresh Worker payload merged with existing `notified` flags).
  - `owned_bags(verdicts) -> set[str]`
  - `rejected(verdicts) -> set[str]`
  - `unnotified_keeps(verdicts) -> list[str]`
  - `mark_notified(verdicts, keys) -> None`

- [ ] **Step 1: Install pytest and write the failing tests**

```bash
.venv/Scripts/python -m pip install pytest
mkdir -p tests && printf '' > tests/__init__.py
```

`tests/test_verdicts.py`:

```python
import json
import verdicts as V


def test_load_missing_returns_empty(tmp_path):
    assert V.load(tmp_path / "nope.json") == {"fetched": None, "listings": {}, "bags": {}}


def test_load_invalid_returns_empty(tmp_path):
    p = tmp_path / "v.json"
    p.write_text("{not json", encoding="utf-8")
    assert V.load(p) == {"fetched": None, "listings": {}, "bags": {}}


def test_save_writes_all_paths(tmp_path):
    v = {"fetched": "t", "listings": {"a": {"v": "no", "t": "t", "notified": False}}, "bags": {}}
    p1, p2 = tmp_path / "s" / "v.json", tmp_path / "d" / "v.json"
    V.save(v, p1, p2)
    assert json.loads(p1.read_text()) == v
    assert json.loads(p2.read_text()) == v


def test_merge_keeps_notified_when_verdict_unchanged():
    existing = {"fetched": "old", "listings": {"k": {"v": "keep", "t": "1", "notified": True}}, "bags": {}}
    fetched = {"listings": {"k": {"v": "keep", "t": "1"}}, "bags": {}}
    out = V.merge(existing, fetched, "now")
    assert out["listings"]["k"] == {"v": "keep", "t": "1", "notified": True}
    assert out["fetched"] == "now"


def test_merge_resets_notified_when_verdict_changed():
    existing = {"fetched": "old", "listings": {"k": {"v": "no", "t": "1", "notified": True}}, "bags": {}}
    fetched = {"listings": {"k": {"v": "keep", "t": "2"}}, "bags": {}}
    assert V.merge(existing, fetched, "now")["listings"]["k"]["notified"] is False


def test_merge_drops_junk_values():
    fetched = {"listings": {"k": {"v": "maybe", "t": "1"}, "j": "garbage"}, "bags": {"b": {"status": "sold"}}}
    out = V.merge(V.load("/nonexistent"), fetched, "now")
    assert out["listings"] == {} and out["bags"] == {}


def test_merge_keeps_bag_statuses():
    fetched = {"listings": {}, "bags": {"chelsea-braided": {"status": "owned", "t": "1"}}}
    out = V.merge(V.load("/nonexistent"), fetched, "now")
    assert out["bags"] == {"chelsea-braided": {"status": "owned", "t": "1"}}


def test_helpers():
    v = {"fetched": None,
         "listings": {"a": {"v": "no", "t": "1", "notified": False},
                      "b": {"v": "keep", "t": "1", "notified": False},
                      "c": {"v": "keep", "t": "1", "notified": True}},
         "bags": {"x": {"status": "owned", "t": "1"}, "y": {"status": "found", "t": "1"}}}
    assert V.owned_bags(v) == {"x"}
    assert V.rejected(v) == {"a"}
    assert V.unnotified_keeps(v) == ["b"]
    V.mark_notified(v, ["b", "zzz"])
    assert v["listings"]["b"]["notified"] is True
    assert V.unnotified_keeps(v) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_verdicts.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'verdicts'`

- [ ] **Step 3: Write `verdicts.py`**

```python
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
    return {"fetched": d.get("fetched"),
            "listings": dict(d.get("listings") or {}),
            "bags": dict(d.get("bags") or {})}


def save(verdicts, *paths):
    for p in paths:
        p = str(p)
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_verdicts.py -q`
Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
git add verdicts.py tests/__init__.py tests/test_verdicts.py
git commit -m "Add verdicts module: load, merge and query her swipe verdicts"
```

---

### Task 2: `finds.py`

**Files:**
- Create: `finds.py`
- Test: `tests/test_finds.py`

**Interfaces:**
- Produces:
  - `load(path) -> list[dict]` (the `finds` array, or `[]`).
  - `update(existing, matched, rejected, now) -> list[dict]` where `matched` items are `{"key", "bag", "listing", "kind"|None, "old_price"|None, "first_seen"}` and `now` is an aware `datetime`.
  - `save(path, finds, bags_cfg, now) -> None` writes `{"generated", "bags", "finds"}`.
  - Constants `MAX = 40`, `KEEP_DAYS = 14`, `STALE_DAYS = 3`.

- [ ] **Step 1: Write the failing tests**

`tests/test_finds.py`:

```python
import json
from datetime import datetime, timedelta, timezone
import finds as F

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)


def L(source="mercari", id="m1", title="Chelsea braided", price=190.0, **kw):
    d = {"source": source, "id": id, "title": title, "price": price, "currency": "USD",
         "url": f"https://x/{id}", "image": f"https://img/{id}.jpg", "seller": None, "condition": None}
    d.update(kw)
    return d


def M(key="mercari:m1", bag="chelsea-braided", kind="new", old_price=None, first_seen=None, **lkw):
    return {"key": key, "bag": bag, "listing": L(id=key.split(":")[1], **lkw), "kind": kind,
            "old_price": old_price, "first_seen": first_seen or NOW.isoformat()}


def test_new_match_becomes_record():
    out = F.update([], [M()], set(), NOW)
    assert len(out) == 1
    r = out[0]
    assert r["key"] == "mercari:m1" and r["bag"] == "chelsea-braided" and r["kind"] == "new"
    assert r["price"] == 190.0 and r["url"] == "https://x/m1" and r["image"] == "https://img/m1.jpg"
    assert r["first_seen"] == NOW.isoformat() and r["last_seen"] == NOW.isoformat()
    assert r["old_price"] is None and r["stale"] is False


def test_existing_record_refreshed_keeps_kind_and_first_seen():
    first = (NOW - timedelta(days=2)).isoformat()
    existing = [{"key": "mercari:m1", "bag": "chelsea-braided", "kind": "deal", "old_price": None,
                 "first_seen": first, "last_seen": first, "price": 100.0, "title": "old"}]
    out = F.update(existing, [M(kind=None, price=95.0, title="new title")], set(), NOW)
    r = out[0]
    assert r["kind"] == "deal" and r["first_seen"] == first
    assert r["price"] == 95.0 and r["title"] == "new title" and r["last_seen"] == NOW.isoformat()


def test_drop_sets_kind_and_old_price():
    first = (NOW - timedelta(days=2)).isoformat()
    existing = [{"key": "mercari:m1", "bag": "chelsea-braided", "kind": "new", "old_price": None,
                 "first_seen": first, "last_seen": first, "price": 200.0}]
    out = F.update(existing, [M(kind="drop", old_price=200.0, price=150.0, first_seen=first)], set(), NOW)
    assert out[0]["kind"] == "drop" and out[0]["old_price"] == 200.0 and out[0]["price"] == 150.0


def test_rejected_removed():
    existing = [dict(F.update([], [M()], set(), NOW)[0])]
    assert F.update(existing, [], {"mercari:m1"}, NOW) == []
    assert F.update([], [M()], {"mercari:m1"}, NOW) == []


def test_old_pruned_and_stale_flagged():
    old_first = (NOW - timedelta(days=15)).isoformat()
    fresh_first = (NOW - timedelta(days=5)).isoformat()
    stale_last = (NOW - timedelta(days=4)).isoformat()
    existing = [
        {"key": "a:1", "bag": "b", "kind": "new", "old_price": None, "first_seen": old_first, "last_seen": NOW.isoformat()},
        {"key": "a:2", "bag": "b", "kind": "new", "old_price": None, "first_seen": fresh_first, "last_seen": stale_last},
    ]
    out = F.update(existing, [], set(), NOW)
    assert [r["key"] for r in out] == ["a:2"]
    assert out[0]["stale"] is True


def test_sorted_newest_first_and_capped():
    matched = [M(key=f"e:{i}", first_seen=(NOW - timedelta(minutes=i)).isoformat()) for i in range(50)]
    out = F.update([], matched, set(), NOW)
    assert len(out) == F.MAX == 40
    assert out[0]["key"] == "e:0" and out[-1]["key"] == "e:39"


def test_save_and_load_roundtrip(tmp_path):
    p = tmp_path / "docs" / "finds.json"
    recs = F.update([], [M()], set(), NOW)
    F.save(p, recs, [{"id": "chelsea-braided", "name": "Chelsea", "deal_price": 120}], NOW)
    doc = json.loads(p.read_text(encoding="utf-8"))
    assert doc["generated"] == NOW.isoformat()
    assert doc["bags"] == {"chelsea-braided": {"name": "Chelsea", "deal_price": 120}}
    assert F.load(p) == recs
    assert F.load(tmp_path / "missing.json") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_finds.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'finds'`

- [ ] **Step 3: Write `finds.py`**

```python
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
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_finds.py -q`
Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add finds.py tests/test_finds.py
git commit -m "Add finds module: merge, prune and write docs/finds.json"
```

---

### Task 3: `notify.py` learns about kept listings

**Files:**
- Modify: `notify.py`
- Test: `tests/test_notify.py`

**Interfaces:**
- Consumes: alert dicts as today (`kind` in new/deal/drop) and kept dicts of the same shape with `kind == "kept"`, `bag` = bag display name.
- Produces: `send(alerts, kept=None) -> list[str]`; `email_lines(alerts, kept) -> list[str]` (pure, tested); `_headline` handles `"kept"`.

- [ ] **Step 1: Write the failing tests**

`tests/test_notify.py`:

```python
import notify as N

A = {"kind": "new", "bag": "Chelsea", "title": "Chelsea satchel", "price": 190.0, "currency": "USD",
     "source": "mercari", "url": "https://x/1", "image": None, "seller": None, "condition": None}
K = {**A, "kind": "kept", "url": "https://x/2", "title": "Kept one"}


def test_headline_kept():
    assert N._headline(K) == "She kept: Chelsea"


def test_email_lines_alerts_then_kept_block():
    lines = N.email_lines([A], [K])
    text = "\n".join(lines)
    assert text.index("New listing: Chelsea") < text.index("She kept") < text.index("Kept one")
    assert "https://x/1" in text and "https://x/2" in text


def test_email_lines_no_kept_block_when_none():
    assert "She kept" not in "\n".join(N.email_lines([A], []))


def test_send_nothing_when_empty():
    assert N.send([], []) == []
    assert N.send([]) == []


def test_discord_color_and_content(monkeypatch):
    posted = []

    class R:
        def raise_for_status(self): pass

    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.test/hook")
    monkeypatch.setattr(N.requests, "post", lambda url, json, timeout: posted.append(json) or R())
    assert N.discord([A] + [K]) is True
    embeds = posted[0]["embeds"]
    assert embeds[0]["color"] == 0xE9A7AC and embeds[1]["color"] == N.KEPT_COLOR
    assert embeds[1]["author"]["name"] == "She kept: Chelsea"
    posted.clear()
    N.discord([K])
    assert posted[0]["content"].startswith("💌")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_notify.py -q`
Expected: FAIL (`KeyError: 'kept'` in `_headline`, `AttributeError: email_lines`, `KEPT_COLOR`)

- [ ] **Step 3: Modify `notify.py`**

Replace `_headline`:

```python
KEPT_COLOR = 0x4E6B3A


def _headline(a):
    kind = {"new": "New listing", "deal": "DEAL", "drop": "Price drop", "kept": "She kept"}[a["kind"]]
    return f"{kind}: {a['bag']}"
```

In `discord`, replace the `colors` line and the `content` line:

```python
    colors = {"new": 0xE9A7AC, "deal": 0xC0392B, "drop": 0xD98F96, "kept": KEPT_COLOR}
```

```python
        chunk = alerts[i:i + 10]
        if any(a["kind"] == "deal" for a in chunk):
            content = "💸 **Deal alert**"
        elif any(a["kind"] != "kept" for a in chunk):
            content = "🍒 New finds"
        else:
            content = "💌 She kept some"
```

(`chunk` replaces the two `alerts[i:i + 10]` slices inside the loop.)

In `ntfy`, the `Tags` line becomes:

```python
            "Tags": "moneybag,cherries" if a["kind"] == "deal" else ("heart" if a["kind"] == "kept" else "cherries"),
```

Replace the body of `email` with a pure helper plus the sender:

```python
def email_lines(alerts, kept):
    lines = [f"{_headline(a)}\n{a['title']}\n{_body_line(a)}\n{a['url']}\n" for a in alerts]
    if kept:
        lines.append("---- She kept ----\n")
        lines += [f"{_headline(a)}\n{a['title']}\n{_body_line(a)}\n{a['url']}\n" for a in kept]
    return lines


def email(alerts, kept=None):
    host = os.environ.get("SMTP_HOST")
    to = os.environ.get("EMAIL_TO")
    if not host or not to:
        return False
    kept = kept or []
    msg = MIMEText("\n".join(email_lines(alerts, kept)))
    deals = sum(1 for a in alerts if a["kind"] == "deal")
    subject = f"Bag tracker: {len(alerts)} new" + (f", {deals} deal" if deals else "") + (f", {len(kept)} kept" if kept else "")
    msg["Subject"] = subject
    msg["From"] = os.environ.get("SMTP_USER", "bag-tracker")
    msg["To"] = to
    with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", "587"))) as s:
        s.starttls()
        if os.environ.get("SMTP_USER"):
            s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
        s.sendmail(msg["From"], [x.strip() for x in to.split(",")], msg.as_string())
    return True
```

Replace `send`:

```python
def send(alerts, kept=None):
    """Fan out to every configured channel. Returns the list of channels that sent."""
    kept = kept or []
    if not alerts and not kept:
        return []
    sent = []
    for name, fn in (("discord", lambda: discord(alerts + kept)),
                     ("ntfy", lambda: ntfy(alerts + kept)),
                     ("telegram", lambda: telegram(alerts + kept)),
                     ("email", lambda: email(alerts, kept))):
        try:
            if fn():
                sent.append(name)
        except Exception as e:  # one channel failing must not block the others
            print(f"[notify] {name} failed: {e}")
    return sent
```

Update the module docstring's first line to: `"""Send alerts and "she kept" notes.  Every channel with its env vars set is used; nothing else is.`

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_notify.py -q`
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add notify.py tests/test_notify.py
git commit -m "Notify: include listings she kept, in every channel"
```

---

### Task 4: `sync_verdicts.py` and the tracker wiring

**Files:**
- Create: `sync_verdicts.py`
- Modify: `tracker.py` (imports; `main()` from the config load to the end)
- Modify: `.gitignore`

**Interfaces:**
- Consumes: Task 1 (`verdicts`), Task 2 (`finds`), Task 3 (`notify.send(alerts, kept)`).
- Produces: `docs/finds.json`, `state/verdicts.json`, `docs/verdicts.json` on disk; env vars `VERDICT_URL`, `VERDICT_TOKEN`.

- [ ] **Step 1: Write `sync_verdicts.py`**

```python
#!/usr/bin/env python3
"""Pull her verdicts from the Worker into state/verdicts.json and docs/verdicts.json.

Runs before tracker.py in both runners. Never fails the run: missing env vars or a dead
Worker leave the previous files in place and exit 0.
"""
import os
import sys
from datetime import datetime, timezone

import requests

import verdicts as verdicts_mod

ROOT = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(ROOT, "state", "verdicts.json")
SITE_PATH = os.path.join(ROOT, "docs", "verdicts.json")


def main():
    url, token = os.environ.get("VERDICT_URL"), os.environ.get("VERDICT_TOKEN")
    if not url or not token:
        print("verdicts: VERDICT_URL / VERDICT_TOKEN not set, skipping", flush=True)
        return 0
    try:
        r = requests.get(url.rstrip("/") + "/v", params={"token": token}, timeout=30)
        r.raise_for_status()
        fetched = r.json()
    except Exception as e:
        print(f"verdicts: fetch failed, keeping previous file: {e}", flush=True)
        return 0
    existing = verdicts_mod.load(STATE_PATH)
    merged = verdicts_mod.merge(existing, fetched, datetime.now(timezone.utc).isoformat())
    verdicts_mod.save(merged, STATE_PATH, SITE_PATH)
    print(f"verdicts: {len(merged['listings'])} listing verdicts, {len(merged['bags'])} bag statuses", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Modify `tracker.py`**

Add after `import notify`:

```python
import finds as finds_mod
import verdicts as verdicts_mod
```

Add after `STATE = ...`:

```python
FINDS = os.path.join(ROOT, "docs", "finds.json")
VERDICTS = os.path.join(ROOT, "state", "verdicts.json")
VERDICTS_SITE = os.path.join(ROOT, "docs", "verdicts.json")
```

In `main()`, replace everything from `groups = {` to the end of the function with:

```python
    verdicts = verdicts_mod.load(VERDICTS)
    all_bag_names = {b["id"]: b["name"] for b in bags}
    owned = verdicts_mod.owned_bags(verdicts) & set(all_bag_names)
    if owned:
        log(f"skipping owned bags: {', '.join(sorted(owned))}")
    bags = [b for b in bags if b["id"] not in owned]
    rejected = verdicts_mod.rejected(verdicts)

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
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()
    alerts = []
    matched_recs = []
    matched = 0
    skipped_rejected = 0
    for key, l in uniq.items():
        if key in rejected:
            skipped_rejected += 1
            continue
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
            matched_recs.append({"key": key, "bag": bag["id"], "listing": l, "kind": kind, "old_price": None, "first_seen": now})
        else:
            old = prev.get("price")
            frac = cfg.get("price_drop_fraction", 0.15)
            akind = None
            if price is not None and old and price <= old * (1 - frac):
                akind = "deal" if (bag.get("deal_price") and price <= bag["deal_price"]) else "drop"
                alerts.append({**base, "kind": akind, "old_price": old})
                prev["price"] = price
            prev["last_seen"] = now
            matched_recs.append({"key": key, "bag": bag["id"], "listing": l, "kind": akind,
                                 "old_price": old if akind else None, "first_seen": prev.get("first_seen") or now})

    finds_list = finds_mod.load(FINDS)
    keep_keys = set(verdicts_mod.unnotified_keeps(verdicts))
    kept = [{**f, "bag": all_bag_names.get(f["bag"], f["bag"]), "bag_id": f["bag"], "kind": "kept"}
            for f in finds_list if f["key"] in keep_keys]

    log(f"{matched} matched a bag, {len(alerts)} alerts, {len(kept)} newly kept"
        + (f", {skipped_rejected} rejected skipped" if skipped_rejected else ""))

    def persist():
        save_state(state, cfg.get("seen_ttl_days", 90))
        finds_mod.save(FINDS, finds_mod.update(finds_list, matched_recs, rejected, now_dt), bags, now_dt)

    if args.init:
        log("init: recorded current listings, no alerts sent")
        persist()
        return

    # Loud first, then newest.
    alerts.sort(key=lambda a: ({"deal": 0, "drop": 1, "new": 2}[a["kind"]], a.get("created") or ""), reverse=False)
    for a in alerts + kept:
        log(f"  [{a['kind']:<4}] {a['bag']:<45} ${a['price'] or 0:>6.0f}  {a['source']:<9} {a['title'][:70]}")

    if args.dry_run:
        log("dry run: nothing sent, state not saved")
        return

    sent = notify.send(alerts, kept)
    if (alerts or kept) and not sent:
        log("WARNING: alerts found but no notification channel is configured; state NOT saved so they resend next run")
        sys.exit(2)
    persist()
    if kept:
        verdicts_mod.mark_notified(verdicts, [k["key"] for k in kept])
        verdicts_mod.save(verdicts, VERDICTS, VERDICTS_SITE)
    log(f"sent via {sent}" if sent else "nothing to send")
```

Update the module docstring: add the line `  python sync_verdicts.py           # pull her swipe verdicts from the Worker (run before tracker.py)`.

- [ ] **Step 3: Verify wiring with a dry run against a fixture verdicts file**

```bash
mkdir -p state docs
cat > state/verdicts.json <<'EOF'
{"fetched": "2026-09-23T00:00:00+00:00",
 "listings": {"mercari:m16817299308": {"v": "no", "t": "2026-09-23T00:00:00+00:00", "notified": false}},
 "bags": {"chelsea-braided": {"status": "owned", "t": "2026-09-23T00:00:00+00:00"}}}
EOF
.venv/Scripts/python tracker.py --sources depop --dry-run 2>&1 | head -20
```

Expected: first log line `skipping owned bags: chelsea-braided`; the depop query list no longer contains `coach chelsea braided` or `coach chelsea optic satchel` (5 depop queries instead of 7); the summary line ends with `0 newly kept`; final line `dry run: nothing sent, state not saved`; `docs/finds.json` does not exist.

Then confirm the init path writes finds:

```bash
.venv/Scripts/python tracker.py --sources depop --init 2>&1 | tail -3
.venv/Scripts/python -c "import json;d=json.load(open('docs/finds.json'));print(d['generated'], len(d['finds']), list(d['bags']))"
git checkout -- state/seen.json; rm docs/finds.json state/verdicts.json
```

Expected: `generated` is a timestamp, `len(finds)` is small (the patchwork matches from Depop), and `chelsea-braided` is absent from the bags list. The last line resets state so the real `--init` at Pass 1 step 6 starts clean.

- [ ] **Step 4: Run the whole suite**

Run: `.venv/Scripts/python -m pytest -q`
Expected: `20 passed`

- [ ] **Step 5: Commit**

```bash
git add sync_verdicts.py tracker.py
git commit -m "Tracker: honour verdicts, write docs/finds.json, notify kept listings"
```

---

### Task 5: Runners commit the new files

**Files:**
- Modify: `run_home.sh`
- Modify: `.github/workflows/track.yml`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `sync_verdicts.py` from Task 4; env vars `VERDICT_URL`, `VERDICT_TOKEN`.

- [ ] **Step 1: Edit `run_home.sh`**

Replace the file with:

```bash
#!/usr/bin/env bash
# Runs the Depop + Mercari pass from a home machine and syncs state with the repo.
# Schedule it every 30 minutes (cron on macOS/Linux, Task Scheduler on Windows; see README).
# Secrets: put DISCORD_WEBHOOK_URL / SMTP_* / VERDICT_* in a file called .env next to this script.
set -euo pipefail
cd "$(dirname "$0")"
[ -f .env ] && set -a && . ./.env && set +a
PY=python3
[ -x .venv/Scripts/python.exe ] && PY=.venv/Scripts/python.exe
[ -x .venv/bin/python ] && PY=.venv/bin/python
git pull --rebase --quiet
"$PY" sync_verdicts.py
"$PY" tracker.py --sources home
git add state/seen.json state/verdicts.json docs/finds.json docs/verdicts.json 2>/dev/null || true
git diff --cached --quiet || { git commit -qm "state(home): $(date -u +%Y-%m-%dT%H:%MZ)"; git push --quiet; }
```

- [ ] **Step 2: Edit `.github/workflows/track.yml`**

In the `Track` step's `env:` block add:

```yaml
          VERDICT_URL: ${{ secrets.VERDICT_URL }}
          VERDICT_TOKEN: ${{ secrets.VERDICT_TOKEN }}
```

In the `Track` step's `run:` block, insert `python sync_verdicts.py` as the first line (before `INIT=""`).

In `Save state`, replace `git add state/seen.json` with:

```yaml
          git add state/seen.json state/verdicts.json docs/finds.json docs/verdicts.json 2>/dev/null || true
```

- [ ] **Step 3: Edit `.gitignore`**

Append:

```
worker/node_modules/
worker/.wrangler/
worker/.dev.vars
```

- [ ] **Step 4: Sanity-check the shell script parses and the YAML loads**

```bash
bash -n run_home.sh && echo "sh ok"
.venv/Scripts/python -c "import yaml;d=yaml.safe_load(open('.github/workflows/track.yml'));print(list(d[True]['schedule'][0].values()), 'yaml ok')"
```

Expected: `sh ok` and `['*/20 * * * *'] yaml ok` (PyYAML parses the `on:` key as `True`).

- [ ] **Step 5: Commit**

```bash
git add run_home.sh .github/workflows/track.yml .gitignore
git commit -m "Runners: sync verdicts first, commit finds and verdict files"
```

---

### Task 6: The Cloudflare Worker

**Files:**
- Create: `worker/wrangler.toml`, `worker/src/index.js`, `worker/package.json`, `worker/.dev.vars` (ignored)

**Interfaces:**
- Produces: `POST /v` and `GET /v` exactly as in the spec; env bindings `VERDICTS` (KV), `TOKEN` (secret), `ALLOWED_ORIGIN` (var).

- [ ] **Step 1: Find the Pages origin**

```bash
gh api user -q .login
```

Expected: your GitHub login, e.g. `marcusm`. The Pages origin is `https://<login>.github.io` (no path). Use it as `ALLOWED_ORIGIN` below. If the repo doesn't exist yet (Pass 1 step 4 pending), the origin is still knowable from the login.

- [ ] **Step 2: Write the Worker files**

`worker/package.json`:

```json
{
  "name": "bag-verdicts",
  "private": true,
  "scripts": { "dev": "wrangler dev", "deploy": "wrangler deploy" },
  "devDependencies": { "wrangler": "^4" }
}
```

`worker/wrangler.toml` (fill `id` in Step 5):

```toml
name = "bag-verdicts"
main = "src/index.js"
compatibility_date = "2026-09-01"

[vars]
ALLOWED_ORIGIN = "https://<login>.github.io"

[[kv_namespaces]]
binding = "VERDICTS"
id = "filled-in-by-step-5"
```

`worker/src/index.js`:

```js
// Verdict store for the bag tracker. Two routes, one KV namespace, one shared token.
//   POST /v  {token, kind: "listing"|"bag", key, value}   -> 204 (value "clear" deletes)
//   GET  /v?token=...                                     -> {listings: {key: {v, t}}, bags: {id: {status, t}}}
const VALUES = {
  listing: new Set(["no", "keep", "clear"]),
  bag: new Set(["wanted", "found", "owned", "clear"]),
};
const TTL_SECONDS = 60 * 24 * 3600;

function cors(env) {
  return {
    "Access-Control-Allow-Origin": env.ALLOWED_ORIGIN,
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
    "Vary": "Origin",
  };
}
const empty = (status, env) => new Response(null, { status, headers: cors(env) });
const json = (obj, status, env) =>
  new Response(JSON.stringify(obj), { status, headers: { "Content-Type": "application/json", ...cors(env) } });

async function listAll(env) {
  const out = { listings: {}, bags: {} };
  let cursor;
  do {
    const page = await env.VERDICTS.list({ cursor });
    for (const { name } of page.keys) {
      const raw = await env.VERDICTS.get(name);
      if (!raw) continue;
      let rec;
      try { rec = JSON.parse(raw); } catch { continue; }
      if (name.startsWith("l:")) out.listings[name.slice(2)] = rec;
      else if (name.startsWith("b:")) out.bags[name.slice(2)] = rec;
    }
    cursor = page.list_complete ? undefined : page.cursor;
  } while (cursor);
  return out;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === "OPTIONS") return empty(204, env);
    if (url.pathname !== "/v") return empty(404, env);

    if (request.method === "GET") {
      if (!env.TOKEN || url.searchParams.get("token") !== env.TOKEN) return empty(401, env);
      return json(await listAll(env), 200, env);
    }

    if (request.method === "POST") {
      let body;
      try { body = await request.json(); } catch { return empty(400, env); }
      if (!body || !env.TOKEN || body.token !== env.TOKEN) return empty(401, env);
      const { kind, key, value } = body;
      if (!VALUES[kind] || typeof key !== "string" || !key || key.length > 200 || !VALUES[kind].has(value)) {
        return empty(400, env);
      }
      const k = (kind === "listing" ? "l:" : "b:") + key;
      if (value === "clear") {
        await env.VERDICTS.delete(k);
        return empty(204, env);
      }
      const t = new Date().toISOString();
      const rec = kind === "listing" ? { v: value, t } : { status: value, t };
      await env.VERDICTS.put(k, JSON.stringify(rec), { expirationTtl: TTL_SECONDS });
      return empty(204, env);
    }

    return empty(405, env);
  },
};
```

- [ ] **Step 3: Generate the token and set up local dev vars**

```bash
TOKEN=$(.venv/Scripts/python -c "import secrets;print(secrets.token_hex(32))")
echo "TOKEN=$TOKEN" > worker/.dev.vars
grep -q '^VERDICT_TOKEN=' .env 2>/dev/null || echo "VERDICT_TOKEN=$TOKEN" >> .env
echo "$TOKEN"
```

Keep the printed token: it goes into the page (Task 8) and the Actions secrets (Task 10).

- [ ] **Step 4: Test locally with wrangler dev**

```bash
cd worker && npm install --silent && (npx wrangler dev --port 8787 --local > ../state/probe/wrangler.log 2>&1 &) && cd ..
sleep 8
T=$(cut -d= -f2 worker/.dev.vars)
curl -s -o /dev/null -w "post keep %{http_code}\n" -X POST localhost:8787/v -H 'Content-Type: application/json' -d "{\"token\":\"$T\",\"kind\":\"listing\",\"key\":\"mercari:m1\",\"value\":\"keep\"}"
curl -s -o /dev/null -w "post bag %{http_code}\n"  -X POST localhost:8787/v -H 'Content-Type: application/json' -d "{\"token\":\"$T\",\"kind\":\"bag\",\"key\":\"chelsea-braided\",\"value\":\"owned\"}"
curl -s -o /dev/null -w "bad token %{http_code}\n" -X POST localhost:8787/v -H 'Content-Type: application/json' -d '{"token":"x","kind":"listing","key":"a","value":"no"}'
curl -s -o /dev/null -w "bad value %{http_code}\n" -X POST localhost:8787/v -H 'Content-Type: application/json' -d "{\"token\":\"$T\",\"kind\":\"listing\",\"key\":\"a\",\"value\":\"maybe\"}"
curl -s "localhost:8787/v?token=$T"; echo
curl -s -o /dev/null -w "clear %{http_code}\n" -X POST localhost:8787/v -H 'Content-Type: application/json' -d "{\"token\":\"$T\",\"kind\":\"listing\",\"key\":\"mercari:m1\",\"value\":\"clear\"}"
curl -s "localhost:8787/v?token=$T"; echo
curl -s -o /dev/null -w "options %{http_code}\n" -X OPTIONS localhost:8787/v
```

Expected, in order: `post keep 204`, `post bag 204`, `bad token 401`, `bad value 400`, then `{"listings":{"mercari:m1":{"v":"keep","t":"..."}},"bags":{"chelsea-braided":{"status":"owned","t":"..."}}}`, `clear 204`, then `{"listings":{},"bags":{"chelsea-braided":{...}}}`, `options 204`. Then stop the dev server: `taskkill //F //IM node.exe //T` (or close its window) — check `tasklist | grep -i node` first so you don't kill unrelated Node processes; if others are running, find the wrangler PID with `netstat -ano | grep :8787` and `taskkill //F //PID <pid>`.

- [ ] **Step 5: Deploy (Marcus runs the login)**

Ask Marcus to run, in the prompt: `! cd worker && npx wrangler login` (opens a browser). Then:

```bash
cd worker
npx wrangler kv namespace create VERDICTS
```

Expected output contains `id = "<32 hex>"`. Paste that id into `wrangler.toml` replacing `filled-in-by-step-5`. Then:

```bash
npx wrangler secret put TOKEN < <(cut -d= -f2 .dev.vars)
npx wrangler deploy
cd ..
```

Expected: `Deployed bag-verdicts ... https://bag-verdicts.<account>.workers.dev`. Record that URL:

```bash
grep -q '^VERDICT_URL=' .env || echo "VERDICT_URL=https://bag-verdicts.<account>.workers.dev" >> .env
```

- [ ] **Step 6: Test live**

```bash
set -a; . ./.env; set +a
curl -s -o /dev/null -w "live bad token %{http_code}\n" "$VERDICT_URL/v?token=nope"
curl -s "$VERDICT_URL/v?token=$VERDICT_TOKEN"; echo
.venv/Scripts/python sync_verdicts.py && cat state/verdicts.json
```

Expected: `live bad token 401`, then `{"listings":{},"bags":{}}`, then `verdicts: 0 listing verdicts, 0 bag statuses` and a file with `"fetched"` set and empty maps. Remove the generated files before committing: `rm state/verdicts.json docs/verdicts.json`.

- [ ] **Step 7: Commit**

```bash
git add worker/package.json worker/wrangler.toml worker/src/index.js
git commit -m "Add the verdict Worker (Cloudflare KV, token + CORS)"
```

---

### Task 7: Reference photos out of the data URIs

**Files:**
- Create: `docs/img/<bag-id>.jpg` (nine files)

**Interfaces:**
- Produces: `docs/img/black-flap-1463.jpg`, `black-soho-satchel.jpg`, `black-soho-flap-shoulder.jpg`, `brown-large-soho-flap.jpg`, `bonnie-satchel.jpg`, `chelsea-braided.jpg`, `brown-soho-satchel.jpg`, `patchwork-leopard-tote.jpg`, `poppy-pink-double-pocket.jpg`.

- [ ] **Step 1: Extract**

```bash
mkdir -p docs/img
.venv/Scripts/python - <<'EOF'
import re, base64, os
src = open("../vintage-coach-bags.html", encoding="utf-8").read()
names = {"blackSatchel": "black-soho-satchel", "blackFlap": "black-flap-1463", "blackSoho": "black-soho-flap-shoulder",
         "bonnie": "bonnie-satchel", "brownSoho": "brown-large-soho-flap", "chelsea": "chelsea-braided",
         "brownSatchel": "brown-soho-satchel", "patchwork": "patchwork-leopard-tote", "poppy": "poppy-pink-double-pocket"}
ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
for key, bag in names.items():
    m = re.search(key + r':\s*"data:(image/[a-z]+);base64,([A-Za-z0-9+/=]+)"', src)
    assert m, key
    path = f"docs/img/{bag}.{ext[m.group(1)]}"
    open(path, "wb").write(base64.b64decode(m.group(2)))
    print(path, os.path.getsize(path))
EOF
ls docs/img
```

Expected: nine files printed with sizes, all `.jpg` (if any are `.png`/`.webp`, keep that extension and use it in the `BAGS` array in Task 8).

- [ ] **Step 2: Commit**

```bash
git add docs/img
git commit -m "Extract her reference photos into docs/img"
```

---

### Task 8: `docs/index.html`

**Files:**
- Create: `docs/index.html`

**Interfaces:**
- Consumes: `finds.json` and `verdicts.json` shapes from the spec; Worker API from Task 6; images from Task 7.
- Produces: the page. Constants `WORKER_URL` and `TOKEN` at the top of the script; `window.WORKER_URL_OVERRIDE` honoured for tests.

- [ ] **Step 1: Write the file**

Fill `WORKER_URL` with the deployed URL from Task 6 Step 5 and `TOKEN` with the token from Task 6 Step 3.

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Vintage Coach Bags</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,500;0,600;1,500&family=EB+Garamond:ital,wght@0,400;0,500;1,400&display=swap" rel="stylesheet">
<style>
  :root {
    box-sizing: border-box;
    --bg: #E9A7AC; --bg-deep: #DB929A; --cream: #F7EBDC; --cream-2: #FBF3E8;
    --cocoa: #5B2A14; --cocoa-soft: #7A4630; --lace: #9C5D58; --rule: rgba(91,42,20,.45);
    --tag-rare: #7A1F2B; --tag-uncommon: #8A5A1E; --tag-common: #4E6B3A;
    --shadow: 0 10px 30px rgba(91,42,20,.18);
    --display: "Cormorant Garamond", Georgia, "Times New Roman", serif;
    --body: "EB Garamond", Georgia, "Times New Roman", serif;
    --nav-h: 64px;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --bg: #4A2A30; --bg-deep: #3C2026; --cream: #F3E3D6; --cream-2: #5A363C;
      --cocoa: #F6E6DA; --cocoa-soft: #E2C7B8; --lace: #D69AA0; --rule: rgba(246,230,218,.45);
      --tag-rare: #F1A6B0; --tag-uncommon: #F0C98A; --tag-common: #B9D9A3;
      --shadow: 0 10px 30px rgba(0,0,0,.35);
    }
  }
  :root[data-theme="dark"] {
    --bg: #4A2A30; --bg-deep: #3C2026; --cream: #F3E3D6; --cream-2: #5A363C;
    --cocoa: #F6E6DA; --cocoa-soft: #E2C7B8; --lace: #D69AA0; --rule: rgba(246,230,218,.45);
    --tag-rare: #F1A6B0; --tag-uncommon: #F0C98A; --tag-common: #B9D9A3;
    --shadow: 0 10px 30px rgba(0,0,0,.35);
  }
  *, *::before, *::after { box-sizing: inherit; }
  html { height: 100%; }
  body {
    margin: 0; min-height: 100%; background: var(--bg); color: var(--cocoa);
    font-family: var(--body); font-size: 1.08rem; line-height: 1.5; -webkit-font-smoothing: antialiased;
    padding: env(safe-area-inset-top, 0px) 16px calc(var(--nav-h) + env(safe-area-inset-bottom, 0px)) 16px;
    overflow-x: hidden;
  }
  a { color: inherit; }
  img { max-width: 100%; display: block; }
  h1, h2, h3 { font-family: var(--display); font-weight: 600; margin: 0; line-height: 1.1; }
  button { font: inherit; color: inherit; cursor: pointer; }
  [hidden] { display: none !important; }

  .top { text-align: center; padding: 18px 0 10px; }
  .top h1 { font-size: clamp(1.9rem, 6vw, 2.6rem); font-weight: 500; letter-spacing: .01em; }
  .top .sub { margin: 4px 0 0; font-style: italic; color: var(--cocoa-soft); font-size: 1rem; }
  main { max-width: 1120px; margin: 0 auto; }
  .tab { display: none; }
  .tab.active { display: block; }

  /* ---------- title box + lace rule ---------- */
  .titlebox {
    border: 1px solid var(--rule); padding: 8px 16px 10px; margin: 26px 0 26px;
    display: flex; align-items: baseline; justify-content: space-between; gap: 16px; flex-wrap: wrap;
  }
  .titlebox h2 { font-size: clamp(1.6rem, 4.5vw, 2.3rem); font-weight: 500; }
  .titlebox .sub { font-style: italic; color: var(--cocoa-soft); }
  .lace-rule {
    height: 10px; margin: -18px 0 22px;
    background: radial-gradient(circle at 5px 5px, var(--lace) 3px, transparent 3.5px) 0 0 / 10px 10px repeat-x;
    opacity: .75;
  }

  /* ---------- review stack ---------- */
  .stack { position: relative; height: min(72vh, 680px); max-width: 480px; margin: 6px auto 0; touch-action: pan-y; }
  .card {
    position: absolute; inset: 0; display: flex; flex-direction: column;
    background: var(--cream-2); border: 1px solid var(--rule); padding: 10px; box-shadow: var(--shadow);
    touch-action: none; user-select: none; -webkit-user-select: none; will-change: transform;
    transition: transform .25s ease, box-shadow .25s ease;
  }
  .card.dragging { transition: none; }
  .card.next { transform: scale(.96) translateY(12px); box-shadow: none; pointer-events: none; }
  .card .photo { position: relative; flex: 1 1 auto; min-height: 0; background: var(--cream); overflow: hidden; }
  .card .photo a { display: block; height: 100%; -webkit-user-drag: none; }
  .card .photo img.main { width: 100%; height: 100%; object-fit: cover; -webkit-user-drag: none; }
  .card .ref {
    position: absolute; left: 10px; bottom: 10px; width: 84px; height: 84px; padding: 3px;
    background: var(--cream-2); border: 1px solid var(--rule); box-shadow: var(--shadow);
  }
  .card .ref img { width: 100%; height: 100%; object-fit: cover; }
  .card .ref::after {
    content: "hers"; position: absolute; left: 0; right: 0; bottom: -1px; font-size: .72rem; text-align: center;
    background: var(--cream-2); color: var(--cocoa-soft); font-style: italic;
  }
  .stamp {
    position: absolute; top: 18px; padding: 4px 12px; font-family: var(--display); font-size: 1.5rem; font-weight: 600;
    border: 2px solid; opacity: 0; transform: rotate(-12deg); transition: opacity .15s;
  }
  .stamp.no { right: 16px; color: #7A1F2B; border-color: #7A1F2B; transform: rotate(12deg); }
  .stamp.keep { left: 16px; color: #4E6B3A; border-color: #4E6B3A; }
  .card.lean-no .stamp.no, .card.lean-keep .stamp.keep { opacity: 1; }
  .card .info { padding: 10px 4px 2px; display: grid; gap: 4px; }
  .card .row { display: flex; flex-wrap: wrap; gap: 6px 12px; align-items: baseline; font-size: 1rem; color: var(--cocoa-soft); }
  .card .price { font-family: var(--display); font-size: 1.6rem; font-weight: 600; color: var(--cocoa); }
  .card .price.deal { color: #C0392B; }
  .card .price.deal::after { content: " deal"; font-size: .95rem; font-style: italic; font-weight: 500; }
  .card .was { text-decoration: line-through; }
  .card .stale { font-style: italic; color: var(--tag-uncommon); }
  .card h3 { font-size: 1.25rem; font-weight: 600; line-height: 1.2; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
  .card .bagline { margin: 0; font-size: .98rem; color: var(--cocoa-soft); font-style: italic; }
  .card .note { margin: 0; font-size: .95rem; color: var(--cocoa-soft); }
  .actions { display: flex; justify-content: center; gap: 28px; margin: 18px 0 8px; }
  .actions button {
    width: 64px; height: 64px; border-radius: 50%; border: 1px solid var(--rule); background: var(--cream-2);
    font-family: var(--display); font-size: 1.7rem; box-shadow: var(--shadow);
  }
  .actions button:hover, .actions button:focus-visible { background: var(--cocoa); color: var(--cream); outline: none; }
  .actions button[disabled] { opacity: .35; cursor: default; }
  .empty { text-align: center; padding: 40px 12px; font-style: italic; color: var(--cocoa-soft); }
  .empty strong { font-style: normal; font-family: var(--display); font-size: 1.5rem; display: block; color: var(--cocoa); font-weight: 500; }
  .saving { text-align: center; font-size: .9rem; font-style: italic; color: var(--tag-uncommon); }

  /* ---------- kept ---------- */
  .kept-group { margin-bottom: 26px; }
  .kept-group h3 { font-size: 1.4rem; margin-bottom: 8px; }
  .krow {
    display: grid; grid-template-columns: 72px 1fr auto; gap: 12px; align-items: center;
    background: var(--cream-2); border: 1px solid var(--rule); padding: 8px; margin-bottom: 8px;
  }
  .krow img { width: 72px; height: 72px; object-fit: cover; }
  .krow .t { font-weight: 500; line-height: 1.25; }
  .krow .m { font-size: .95rem; color: var(--cocoa-soft); }
  .krow .m .deal { color: #C0392B; }
  .krow .x { border: 1px solid var(--rule); background: none; padding: 4px 10px; font-size: .9rem; }
  .krow .x:hover { background: var(--cocoa); color: var(--cream); }

  /* ---------- bags ---------- */
  .bags { display: grid; gap: 28px; grid-template-columns: repeat(auto-fit, minmax(270px, 1fr)); align-items: start; }
  .bag { display: grid; gap: 12px; }
  .bag .frame { background: var(--cream-2); border: 1px solid var(--rule); padding: 10px; box-shadow: var(--shadow); }
  .bag .frame img { width: 100%; aspect-ratio: 1 / 1; object-fit: cover; }
  .bag h3 { font-size: 1.55rem; font-weight: 600; }
  .meta { display: flex; flex-wrap: wrap; gap: 8px 14px; align-items: center; font-size: .98rem; color: var(--cocoa-soft); }
  .tag { font-style: italic; }
  .tag.rare { color: var(--tag-rare); } .tag.uncommon { color: var(--tag-uncommon); } .tag.common { color: var(--tag-common); }
  .bag p { margin: 0; }
  .bag .note { color: var(--cocoa-soft); font-size: 1rem; }
  .hunt { display: flex; flex-wrap: wrap; gap: 6px 8px; margin-top: 2px; }
  .hunt a { text-decoration: none; border: 1px solid var(--rule); padding: 4px 10px; font-size: .95rem; background: var(--cream-2); color: var(--cocoa); }
  .hunt a:hover, .hunt a:focus-visible { background: var(--cocoa); color: var(--cream); outline: none; }
  .status { display: flex; align-items: center; gap: 8px; font-size: .98rem; color: var(--cocoa-soft); flex-wrap: wrap; }
  .seg { display: inline-flex; border: 1px solid var(--rule); }
  .seg button { background: var(--cream-2); border: 0; border-right: 1px solid var(--rule); padding: 4px 10px; font-size: .95rem; }
  .seg button:last-child { border-right: 0; }
  .seg button.on { background: var(--cocoa); color: var(--cream); }
  .owned-note { font-size: .9rem; font-style: italic; color: var(--cocoa-soft); }

  /* ---------- prose ---------- */
  details.fold { border-top: 1px solid var(--rule); margin-top: 22px; }
  details.fold summary { cursor: pointer; padding: 12px 0; font-family: var(--display); font-size: 1.6rem; font-weight: 500; list-style: none; display: flex; justify-content: space-between; align-items: baseline; }
  details.fold summary::-webkit-details-marker { display: none; }
  details.fold summary::after { content: "+"; font-size: 1.6rem; }
  details.fold[open] summary::after { content: "−"; }
  details.fold summary .sub { font-family: var(--body); font-size: 1rem; font-style: italic; color: var(--cocoa-soft); font-weight: 400; }
  details.fold .body { padding-bottom: 18px; }
  .cols { display: grid; gap: 22px 40px; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); }
  .platform { border-top: 1px solid var(--rule); padding-top: 12px; }
  .platform h3 { font-size: 1.5rem; }
  .platform p { margin: 6px 0 0; }
  .platform .how { font-style: italic; color: var(--cocoa-soft); }
  .platform a.go { display: inline-block; margin-top: 8px; font-size: .98rem; }
  ul.check { padding-left: 1.2em; margin: 0; }
  ul.check li { margin: 6px 0; }
  .callout { background: var(--cream-2); border: 1px solid var(--rule); padding: 16px 20px; margin-top: 22px; }
  .callout p { margin: 0; }
  .recs { display: grid; gap: 18px 32px; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); }
  .rec { border-top: 1px solid var(--rule); padding-top: 10px; }
  .rec h3 { font-size: 1.5rem; }
  .rec .why { margin: 4px 0 0; }
  .rec .range { margin: 4px 0 0; color: var(--cocoa-soft); font-style: italic; font-size: 1rem; }
  .rec .hunt { margin-top: 8px; }

  /* ---------- bottom tabs ---------- */
  .tabs {
    position: fixed; left: 0; right: 0; bottom: 0; z-index: 5; display: flex;
    background: var(--cream); border-top: 1px solid rgba(91,42,20,.35);
    padding-bottom: env(safe-area-inset-bottom, 0px);
  }
  .tabs button {
    flex: 1; height: var(--nav-h); background: none; border: 0; color: #5B2A14;
    font-family: var(--display); font-size: 1.2rem; font-weight: 600; position: relative;
  }
  .tabs button.on { color: #5B2A14; box-shadow: inset 0 3px 0 #5B2A14; }
  .badge {
    display: inline-block; min-width: 22px; padding: 0 6px; margin-left: 6px; border-radius: 11px;
    background: #7A1F2B; color: #F7EBDC; font-family: var(--body); font-size: .85rem; line-height: 22px; vertical-align: middle;
  }
  .badge:empty { display: none; }

  .toast {
    position: fixed; left: 50%; transform: translateX(-50%); bottom: calc(var(--nav-h) + 14px + env(safe-area-inset-bottom, 0px));
    z-index: 6; display: flex; gap: 14px; align-items: center;
    background: #5B2A14; color: #F7EBDC; padding: 8px 14px; box-shadow: var(--shadow); font-size: 1rem;
  }
  .toast button { background: none; border: 1px solid rgba(247,235,220,.6); color: inherit; padding: 2px 10px; }
  .lightbox { position: fixed; inset: 0; z-index: 7; background: rgba(60,20,10,.85); display: grid; place-items: center; padding: 24px; }
  .lightbox img { max-height: 90vh; max-width: 100%; border: 6px solid var(--cream-2); }
  @media (prefers-reduced-motion: reduce) { .card { transition: none; } }
</style>
</head>
<body>
<header class="top">
  <h1>Vintage Coach Bags</h1>
  <p class="sub" id="subline">Loading the latest finds…</p>
</header>

<main>
  <section id="tab-review" class="tab active" aria-label="Review">
    <div id="stack" class="stack"></div>
    <div class="actions">
      <button id="btn-no" type="button" aria-label="Not it">✕</button>
      <button id="btn-keep" type="button" aria-label="Keep">♥</button>
    </div>
    <p id="saving" class="saving" hidden>Some verdicts haven't saved yet. They'll send when you're back online.</p>
    <div id="review-empty" class="empty" hidden></div>
  </section>

  <section id="tab-kept" class="tab" aria-label="Kept">
    <div class="titlebox"><h2>Kept</h2><span class="sub">the ones worth a closer look</span></div>
    <div class="lace-rule"></div>
    <div id="kept"></div>
  </section>

  <section id="tab-bags" class="tab" aria-label="Bags">
    <div class="titlebox"><h2>Black Bags</h2><span class="sub">the three she reaches for first</span></div>
    <div class="lace-rule"></div>
    <div class="bags" data-group="black"></div>
    <div class="titlebox"><h2>Brown Bags</h2><span class="sub">khaki, mahogany and chocolate</span></div>
    <div class="lace-rule"></div>
    <div class="bags" data-group="brown"></div>
    <div class="titlebox"><h2>Misc.</h2><span class="sub">the two rare ones</span></div>
    <div class="lace-rule"></div>
    <div class="bags" data-group="misc"></div>

    <details class="fold">
      <summary>Where to Hunt <span class="sub">and how each place tells you something new showed up</span></summary>
      <div class="body">
        <div class="cols">
          <div class="platform"><h3>Gem</h3><p>One search across eBay, Poshmark, Depop, Etsy, Mercari, The RealReal and hundreds of small vintage shops. The best first stop for anything on this list.</p><p class="how">Make a free account, search a bag, then save the search and turn on alerts.</p><a class="go" href="https://gem.app" target="_blank" rel="noopener">gem.app</a></div>
          <div class="platform"><h3>eBay</h3><p>The deepest supply of Y2K Coach by far, and the only place with reliable sold-price history.</p><p class="how">Save a search sorted by "newly listed"; eBay emails once a day when new matches appear. Always check "sold items" before paying asking price.</p><a class="go" href="https://www.ebay.com/sch/i.html?_nkw=vintage+coach+signature+bag&_sop=10" target="_blank" rel="noopener">ebay.com</a></div>
          <div class="platform"><h3>Mercari</h3><p>Cheaper than eBay for common bags, and sellers accept offers freely.</p><p class="how">Save a search and turn on notifications under Settings; pushes arrive with a delay, email arrives as a daily digest.</p><a class="go" href="https://www.mercari.com/search/?keyword=vintage%20coach%20signature" target="_blank" rel="noopener">mercari.com</a></div>
          <div class="platform"><h3>Poshmark</h3><p>Lots of Coach, priced high but everyone haggles. Bundle two items from one closet for a discount.</p><p class="how">Tap the star to save a search. New matches only show as a red dot in your Saved tab, so open the app every day or two.</p><a class="go" href="https://poshmark.com/search?query=vintage%20coach%20signature&department=Women" target="_blank" rel="noopener">poshmark.com</a></div>
          <div class="platform"><h3>Depop</h3><p>Where the "cherry charm on a Soho flap" crowd actually sells. Styled photos, quick turnover.</p><p class="how">Star a search to save it and opt in to notifications; Depop sends one weekly push per saved search, and saved searches can't be edited, only remade.</p><a class="go" href="https://www.depop.com/search/?q=vintage%20coach%20signature" target="_blank" rel="noopener">depop.com</a></div>
          <div class="platform"><h3>Etsy</h3><p>Curated vintage sellers with good photos and honest condition notes. Slightly pricier, far fewer fakes.</p><p class="how">Favorite the shops that keep turning up; they restock in batches.</p><a class="go" href="https://www.etsy.com/search?q=vintage%20coach%20signature%20bag" target="_blank" rel="noopener">etsy.com</a></div>
          <div class="platform"><h3>Beni</h3><p>A free app and browser extension that searches 40+ resale sites at once.</p><p class="how">Set an alert for a bag and it emails you when a match appears. A good backup to Gem.</p><a class="go" href="https://www.joinbeni.com" target="_blank" rel="noopener">joinbeni.com</a></div>
        </div>
        <div class="callout"><p>Search by style number wherever you can ("Coach 1463"), then by the name sellers actually use ("Coach Soho flap black"), then by the loose description ("Coach signature flap silver buckle"). Rare bags are usually listed by people who don't know what they have.</p></div>
      </div>
    </details>

    <details class="fold">
      <summary>Before You Buy <span class="sub">a two-minute check that saves the disappointment</span></summary>
      <div class="body">
        <div class="cols">
          <div><h3>Ask the seller for</h3><ul class="check">
            <li>A photo of the creed patch inside (the leather stamp with "No." and a code like F05K-1463). The last four digits are the style number.</li>
            <li>The bottom corners. Jacquard wears through there first and it can't be fixed.</li>
            <li>The inside lining under a light. Pen marks and makeup stains hide in the shadows.</li>
            <li>Hardware close-ups. Silver plating flakes on the buckles and rings and shows brass underneath.</li>
          </ul></div>
          <div><h3>Signs it's real</h3><ul class="check">
            <li>The Cs on the front are mirrored in pairs and sit centered and symmetrical, not sliced off at the seams.</li>
            <li>Stitching is even and tight, especially where the leather trim meets fabric.</li>
            <li>The hangtag is a plain leather lozenge with "COACH" stamped, on a chain or ring.</li>
            <li>Under-$40 "new with tags" is a warning sign. These were $200 to $400 bags new.</li>
          </ul></div>
        </div>
        <div class="callout"><p>A fair price: check eBay's sold listings for the same style, then aim for the middle. Ask about musty smell before buying; jacquard holds onto it. A little handle creasing and light corner scuffing are normal for twenty-year-old bags and are fine to pay less for.</p></div>
      </div>
    </details>

    <details class="fold">
      <summary>Beyond Coach <span class="sub">same era, same spirit, same budget</span></summary>
      <div class="body"><div class="recs" data-group="recs1"></div></div>
    </details>

    <details class="fold">
      <summary>Beyond Coach, a step up <span class="sub">the logo canvases these bags were dreaming of</span></summary>
      <div class="body">
        <div class="recs" data-group="recs2"></div>
        <div class="callout"><p>And the cherries: the bag charm in every one of these photos is the thread that ties the whole collection together. Coach made its own enamel and acrylic cherry charms in the same years; Juicy Couture and Betsey Johnson made louder ones.
          <span class="hunt" style="display:inline-flex;margin-left:8px;vertical-align:middle">
            <a href="https://www.ebay.com/sch/i.html?_nkw=coach+cherry+bag+charm&_sop=10" target="_blank" rel="noopener">eBay</a>
            <a href="https://www.depop.com/search/?q=cherry%20bag%20charm" target="_blank" rel="noopener">Depop</a>
            <a href="https://www.etsy.com/search?q=cherry%20bag%20charm" target="_blank" rel="noopener">Etsy</a>
          </span></p></div>
      </div>
    </details>

    <details class="fold">
      <summary>If You Only Do Three Things</summary>
      <div class="body">
        <ul class="check" style="font-size:1.15rem">
          <li>Make a Gem account and save one search per bag with alerts on. That covers most of the internet at once.</li>
          <li>Save the two rare ones (the leopard patchwork tote and the pink Poppy) on eBay, Mercari and Depop too. Those are the ones that vanish in an hour.</li>
          <li>Before paying, look at eBay's sold listings for that style. Asking prices on Poshmark are a wish, not a price.</li>
        </ul>
        <div class="callout"><p>Your wanted / found / owned choices and your swipes are shared with the tracker, so marking a bag owned stops the searching for it, and anything you swipe away stays gone.</p></div>
      </div>
    </details>
  </section>
</main>

<nav class="tabs" aria-label="Sections">
  <button type="button" data-tab="review" class="on">Review<span class="badge" id="badge"></span></button>
  <button type="button" data-tab="kept">Kept</button>
  <button type="button" data-tab="bags">Bags</button>
</nav>
<div id="toast" class="toast" hidden><span id="toast-text"></span><button id="undo" type="button">Undo</button></div>
<div id="lightbox" class="lightbox" hidden><img id="lightbox-img" alt="Her reference photo"></div>

<script>
(function () {
  // ---------- config ----------
  var WORKER_URL = window.WORKER_URL_OVERRIDE || "https://bag-verdicts.REPLACE-ME.workers.dev";
  var TOKEN = "REPLACE-ME";
  var SRC = { ebay: "eBay", poshmark: "Poshmark", mercari: "Mercari", depop: "Depop" };

  // ---------- her bags (ids match config.yaml) ----------
  var BAGS = [
    { id: "black-soho-satchel", group: "black", img: "img/black-soho-satchel.jpg",
      name: "Soho Signature Satchel (Boston)", style: "mid-2000s, silver hardware, buckle-tab pockets",
      rarity: "common", price: "$60 to $130",
      note: "Turns up weekly. Hold out for clean corners and no lining stains.",
      q: "Coach Soho signature satchel black" },
    { id: "black-flap-1463", group: "black", img: "img/black-flap-1463.jpg",
      name: "Signature Flap, #1463 / #1444", style: "1463 is the medium (12 × 7 in), 1444 the small (9 × 6 in)",
      rarity: "common", price: "$80 to $180; new-with-tags runs higher",
      note: "Search the number itself. The medium is far more common than the small.",
      q: "Coach 1463 black signature flap", q2: "Coach 1444 black signature flap" },
    { id: "black-soho-flap-shoulder", group: "black", img: "img/black-soho-flap-shoulder.jpg",
      name: "Soho Signature Flap Shoulder Bag", style: "ring-linked leather strap, buckle flap, 2005 to 2007",
      rarity: "common", price: "$50 to $120",
      note: "Many sizes exist; the strap with the metal rings is the tell for this one.",
      q: "Coach Soho signature flap shoulder bag black silver" },
    { id: "brown-large-soho-flap", group: "brown", img: "img/brown-large-soho-flap.jpg",
      name: "Large Soho Flap, khaki and mahogany", style: "brass buckle, suede-trimmed flap",
      rarity: "common", price: "$50 to $120",
      note: "The most plentiful Coach bag of its decade. Be picky about the suede on the flap.",
      q: "Coach Soho signature flap khaki brown brass" },
    { id: "bonnie-satchel", group: "brown", img: "img/bonnie-satchel.jpg",
      name: "Bonnie Satchel Shoulder Bag, brown", style: "dark brown Signature, silver rings, buckled straps",
      rarity: "uncommon", price: "$60 to $140",
      note: "Sellers name this one inconsistently. Search by description, not just the name.",
      q: "Coach signature satchel brown silver buckle straps", q2: "Coach Bonnie satchel brown" },
    { id: "chelsea-braided", group: "brown", img: "img/chelsea-braided.jpg",
      name: "Chelsea Optic Signature Satchel, braided handles", style: "turn-lock flap, optic C jacquard, 2005 to 2006",
      rarity: "rare", price: "$90 to $200",
      note: "The braided handles are the rare part; plain-handle Chelsea satchels are everywhere. Ask for a creed photo.",
      q: "Coach Chelsea optic signature braided handle satchel", q2: "Coach Chelsea turnlock satchel brown" },
    { id: "brown-soho-satchel", group: "brown", img: "img/brown-soho-satchel.jpg",
      name: "Soho Signature Satchel (Boston), khaki", style: "silver hardware, twin buckle tabs, same body as the black",
      rarity: "common", price: "$60 to $140",
      note: "If the black one shows up first at a good price, this is the same bag in a different colorway.",
      q: "Coach Soho signature satchel khaki brown" },
    { id: "patchwork-leopard-tote", group: "misc", img: "img/patchwork-leopard-tote.jpg",
      name: "Signature Patchwork Gallery Tote, leopard patch", style: "2006 holiday patchwork, brass hardware; style numbers seen: 11495, 12843, 12527",
      rarity: "rare", price: "$80 to $200",
      note: "Patchwork totes are common; this exact mix with the leopard and snake patches is not. Search 'leopard' and 'cheetah' both.",
      q: "Coach patchwork tote leopard", q2: "Coach signature patchwork gallery tote cheetah" },
    { id: "poppy-pink-double-pocket", group: "misc", img: "img/poppy-pink-double-pocket.jpg",
      name: "Poppy Signature Double Pocket, pink trim", style: "khaki jacquard, pink patent trim and push-locks, 2009 to 2010",
      rarity: "rare", price: "$60 to $150",
      note: "Poppy was a short-lived line and pink trim was one colorway among many. Expect months, not weeks.",
      q: "Coach Poppy signature pink double pocket", q2: "Coach Poppy khaki pink patent pocket bag" }
  ];
  var BAG_BY_ID = {};
  BAGS.forEach(function (b) { BAG_BY_ID[b.id] = b; });

  var RECS1 = [
    { name: "Dooney & Bourke Signature and 'It' bags", why: "The other monogram canvas of 2004. The rainbow-logo It bags are having the same comeback her Coach bags are.", range: "$40 to $150", q: "Dooney Bourke It bag signature vintage" },
    { name: "Kate Spade Sam bag", why: "Boxy, black, nylon, a little prim. The same quiet confidence as her black Soho flap, without the logo.", range: "$40 to $120 vintage; reissued new", q: "Kate Spade Sam bag vintage" },
    { name: "Juicy Couture velour Daydreamer", why: "Louder cousin of the pink Poppy: brown or pink velour, gold charms, ridiculous and perfect.", range: "$50 to $150", q: "Juicy Couture Daydreamer velour bag" },
    { name: "Michael Kors early monogram (2005 to 2010)", why: "Brown Signature-style jacquard with heavy gold hardware. Closest in feel to her Chelsea satchel.", range: "$40 to $120", q: "Michael Kors monogram satchel vintage brown" },
    { name: "Betsey Johnson novelty bags", why: "For the cherry-charm side of her taste. Hearts, bows, fruit, in leather that has aged surprisingly well.", range: "$40 to $120", q: "Betsey Johnson vintage bag cherry" },
    { name: "Coach's own re-issue of the Soho Flap", why: "Coach brought the 2006 Soho Flap back in Signature jacquard. New, guaranteed real, and it looks right next to the vintage ones.", range: "around $400 new", q: "Coach Soho flap signature jacquard CJ814", site: ["coach.com", "https://www.coach.com/products/soho-flap-bag-in-signature-jacquard/CJ814.html"] }
  ];
  var RECS2 = [
    { name: "Gucci GG canvas Boston or Abbey", why: "The GG monogram satchel is what the Soho Boston was quietly nodding at. Brown canvas, leather trim, brass.", range: "$300 to $800", q: "Gucci GG canvas Boston bag vintage" },
    { name: "Fendi Zucca baguette or Mama", why: "Brown-on-tan logo jacquard with a flap and one big buckle. Her flap bags, one tier up.", range: "$400 to $900", q: "Fendi Zucca baguette vintage" },
    { name: "Burberry Nova Check shoulder bag", why: "Beige check instead of Cs, same 2000s shoulder-bag shapes, and cheaper than people assume.", range: "$150 to $400", q: "Burberry Nova check shoulder bag vintage" },
    { name: "Céline Macadam", why: "The under-the-radar one: 1970s to 2000s brown logo canvas from before Céline got minimal. Boston bags and flaps both exist.", range: "$300 to $700", q: "Celine Macadam vintage bag" },
    { name: "Dior Trotter (Diorissimo) canvas", why: "Navy or brown logo jacquard, 2000 to 2005, with Boston bags and pochettes that echo her satchels.", range: "$400 to $1,000", q: "Dior Trotter Boston bag vintage" },
    { name: "Louis Vuitton Mini Lin Speedy", why: "Soft woven monogram instead of coated canvas, in ebène brown. The gentlest way into LV and the closest in texture to jacquard.", range: "$700 to $1,200", q: "Louis Vuitton Mini Lin Speedy ebene" }
  ];

  // ---------- helpers ----------
  function $(id) { return document.getElementById(id); }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function enc(s) { return encodeURIComponent(s); }
  function links(q) {
    return [
      ["eBay", "https://www.ebay.com/sch/i.html?_nkw=" + enc(q).replace(/%20/g, "+") + "&_sop=10"],
      ["Poshmark", "https://poshmark.com/search?query=" + enc(q) + "&department=Women"],
      ["Mercari", "https://www.mercari.com/search/?keyword=" + enc(q)],
      ["Depop", "https://www.depop.com/search/?q=" + enc(q)],
      ["Etsy", "https://www.etsy.com/search?q=" + enc(q)]
    ];
  }
  function huntHTML(q) {
    return '<div class="hunt">' + links(q).map(function (l) {
      return '<a href="' + l[1] + '" target="_blank" rel="noopener">' + l[0] + '</a>';
    }).join("") + '</div>';
  }
  function readLS(k, d) { try { var v = localStorage.getItem("finds:" + k); return v ? JSON.parse(v) : d; } catch (e) { return d; } }
  function writeLS(k, v) { try { localStorage.setItem("finds:" + k, JSON.stringify(v)); } catch (e) {} }
  function money(n) { return n == null ? "price not listed" : "$" + Math.round(n); }
  function when(iso) {
    if (!iso) return "";
    var d = new Date(iso); if (isNaN(d)) return "";
    return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  }

  // ---------- state ----------
  var finds = [], bagsMeta = {}, generated = null, findsMissing = false;
  var verdicts = { fetched: null, listings: {}, bags: {} };
  var overlay = readLS("overlay", {});       // listing key -> {v: "no"|"keep"|null, t}
  var bagOverlay = readLS("bagOverlay", {}); // bag id -> {status, t}
  var queue = readLS("queue", []);           // unsent posts
  var history = [];                          // for undo
  var flushing = false;

  function verdictFor(key) {
    var o = overlay[key], s = verdicts.listings[key];
    if (o && (!s || o.t >= (s.t || ""))) return o.v;
    return s ? s.v : null;
  }
  function bagStatus(id) {
    var o = bagOverlay[id], s = verdicts.bags[id];
    if (o && (!s || o.t >= (s.t || ""))) return o.status;
    return s ? s.status : "wanted";
  }
  function pruneOverlay() {
    var fetched = verdicts.fetched || "";
    Object.keys(overlay).forEach(function (k) {
      var o = overlay[k], s = verdicts.listings[k];
      if (s && (s.t || "") >= o.t) delete overlay[k];
      else if (!s && o.v === null && fetched >= o.t) delete overlay[k];
    });
    Object.keys(bagOverlay).forEach(function (k) {
      var o = bagOverlay[k], s = verdicts.bags[k];
      if (s && (s.t || "") >= o.t) delete bagOverlay[k];
    });
    writeLS("overlay", overlay); writeLS("bagOverlay", bagOverlay);
  }

  // ---------- worker ----------
  function post(kind, key, value) {
    queue.push({ kind: kind, key: key, value: value });
    writeLS("queue", queue);
    flush();
  }
  function setSaving(on) { $("saving").hidden = !on; }
  function flush() {
    if (flushing || !queue.length || !WORKER_URL || !TOKEN) return;
    flushing = true;
    var item = queue[0];
    fetch(WORKER_URL + "/v", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: TOKEN, kind: item.kind, key: item.key, value: item.value })
    }).then(function (r) {
      if (r.status === 204 || r.status === 400) { queue.shift(); writeLS("queue", queue); return true; }
      throw new Error("status " + r.status);
    }).then(function () {
      flushing = false; setSaving(false);
      if (queue.length) flush();
    }).catch(function () {
      flushing = false; setSaving(true);
    });
  }
  window.addEventListener("online", flush);

  // ---------- verdicts ----------
  function setVerdict(key, v) {
    overlay[key] = { v: v, t: new Date().toISOString() }; writeLS("overlay", overlay);
    post("listing", key, v);
    history.push(key);
    showToast(v === "no" ? "Not it" : "Kept");
  }
  function undo() {
    var key = history.pop(); if (!key) return;
    overlay[key] = { v: null, t: new Date().toISOString() }; writeLS("overlay", overlay);
    post("listing", key, "clear");
    hideToast(); render();
  }
  function setBag(id, status) {
    bagOverlay[id] = { status: status, t: new Date().toISOString() }; writeLS("bagOverlay", bagOverlay);
    post("bag", id, status);
    renderBags();
  }

  var toastTimer = null;
  function showToast(text) {
    $("toast-text").textContent = text; $("toast").hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(hideToast, 5000);
  }
  function hideToast() { $("toast").hidden = true; }
  $("undo").addEventListener("click", undo);

  // ---------- review ----------
  function unreviewed() { return finds.filter(function (f) { return !verdictFor(f.key); }); }

  function cardHTML(f) {
    var meta = bagsMeta[f.bag] || {}, def = BAG_BY_ID[f.bag];
    var deal = f.kind === "deal" || (meta.deal_price != null && f.price != null && f.price <= meta.deal_price);
    var extras = [f.condition, f.seller ? "seller " + f.seller : null].filter(Boolean).join(" · ");
    return '<div class="photo">' +
      '<a href="' + esc(f.url) + '" target="_blank" rel="noopener" draggable="false">' +
      '<img class="main" src="' + esc(f.image || "") + '" alt="" draggable="false"></a>' +
      (def ? '<button class="ref" type="button" aria-label="Her reference photo" data-img="' + esc(def.img) + '"><img src="' + esc(def.img) + '" alt="" draggable="false"></button>' : '') +
      '<span class="stamp no">Not it</span><span class="stamp keep">Keep</span></div>' +
      '<div class="info"><div class="row">' +
      '<span class="price' + (deal ? ' deal' : '') + '">' + money(f.price) + '</span>' +
      (f.old_price != null ? '<span class="was">' + money(f.old_price) + '</span>' : '') +
      '<span class="src">' + (SRC[f.source] || esc(f.source)) + '</span>' +
      (f.stale ? '<span class="stale">may be sold</span>' : '') +
      '</div><h3>' + esc(f.title || "(no title)") + '</h3>' +
      '<p class="bagline">Matched to: ' + esc(meta.name || (def && def.name) || f.bag) + '</p>' +
      (extras ? '<p class="note">' + esc(extras) + '</p>' : '') + '</div>';
  }

  function renderReview() {
    var stack = $("stack"), list = unreviewed();
    stack.innerHTML = "";
    var empty = $("review-empty");
    $("btn-no").disabled = $("btn-keep").disabled = !list.length;
    if (!list.length) {
      stack.hidden = true; empty.hidden = false;
      empty.innerHTML = findsMissing
        ? '<strong>The tracker hasn’t run yet.</strong>Come back after the first pass.'
        : '<strong>Nothing new to review.</strong>' + (generated ? 'Last checked ' + esc(when(generated)) + '.' : '');
      return;
    }
    stack.hidden = false; empty.hidden = true;
    list.slice(0, 2).reverse().forEach(function (f, i, arr) {
      var card = document.createElement("article");
      card.className = "card" + (i === arr.length - 1 ? "" : " next");
      card.dataset.key = f.key;
      card.innerHTML = cardHTML(f);
      stack.appendChild(card);
      if (i === arr.length - 1) attachDrag(card, f.key);
    });
  }

  function fly(card, dir, cb) {
    var w = card.offsetWidth || 320;
    card.classList.remove("dragging");
    card.style.transition = "transform .25s ease";
    card.style.transform = "translate(" + (dir * w * 1.5) + "px, 0) rotate(" + (dir * 30) + "deg)";
    setTimeout(cb, 260);
  }
  function decide(v) {
    var card = $("stack").querySelector(".card:not(.next)");
    if (!card) return;
    var key = card.dataset.key;
    fly(card, v === "no" ? -1 : 1, function () { setVerdict(key, v); render(); });
  }
  $("btn-no").addEventListener("click", function () { decide("no"); });
  $("btn-keep").addEventListener("click", function () { decide("keep"); });

  function attachDrag(card, key) {
    var startX = 0, startY = 0, dx = 0, dy = 0, dragging = false, moved = false, startT = 0;
    card.addEventListener("pointerdown", function (e) {
      if (e.button) return;
      if (e.target.closest(".ref")) return;
      dragging = true; moved = false; dx = dy = 0; startX = e.clientX; startY = e.clientY; startT = Date.now();
      card.setPointerCapture(e.pointerId); card.classList.add("dragging");
    });
    card.addEventListener("pointermove", function (e) {
      if (!dragging) return;
      dx = e.clientX - startX; dy = e.clientY - startY;
      if (Math.abs(dx) > 6 || Math.abs(dy) > 6) moved = true;
      card.style.transform = "translate(" + dx + "px, " + (dy * 0.3) + "px) rotate(" + (dx / 18) + "deg)";
      card.classList.toggle("lean-no", dx < -40);
      card.classList.toggle("lean-keep", dx > 40);
    });
    function end(e) {
      if (!dragging) return;
      dragging = false;
      card.classList.remove("dragging", "lean-no", "lean-keep");
      var w = card.offsetWidth || 320, dt = Math.max(Date.now() - startT, 1), vel = Math.abs(dx) / dt;
      if (Math.abs(dx) > w / 3 || (vel > 0.6 && Math.abs(dx) > 40)) {
        var v = dx < 0 ? "no" : "keep";
        fly(card, dx < 0 ? -1 : 1, function () { setVerdict(key, v); render(); });
      } else {
        card.style.transform = "";
      }
    }
    card.addEventListener("pointerup", end);
    card.addEventListener("pointercancel", end);
    card.addEventListener("click", function (e) {
      if (moved) { e.preventDefault(); return; }
      var ref = e.target.closest(".ref");
      if (ref) { e.preventDefault(); $("lightbox-img").src = ref.dataset.img; $("lightbox").hidden = false; }
    });
  }
  $("lightbox").addEventListener("click", function () { $("lightbox").hidden = true; });

  // ---------- kept ----------
  function renderKept() {
    var host = $("kept"), kept = finds.filter(function (f) { return verdictFor(f.key) === "keep"; });
    host.innerHTML = "";
    if (!kept.length) {
      host.innerHTML = '<div class="empty"><strong>Nothing kept yet.</strong>Swipe right on a find to keep it here.</div>';
      return;
    }
    var order = Object.keys(bagsMeta).length ? Object.keys(bagsMeta) : BAGS.map(function (b) { return b.id; });
    var groups = {};
    kept.forEach(function (f) { (groups[f.bag] = groups[f.bag] || []).push(f); });
    Object.keys(groups).sort(function (a, b) { return order.indexOf(a) - order.indexOf(b); }).forEach(function (bag) {
      var meta = bagsMeta[bag] || {}, def = BAG_BY_ID[bag];
      var g = document.createElement("div"); g.className = "kept-group";
      g.innerHTML = '<h3>' + esc(meta.name || (def && def.name) || bag) + '</h3>';
      groups[bag].forEach(function (f) {
        var deal = f.kind === "deal" || (meta.deal_price != null && f.price != null && f.price <= meta.deal_price);
        var row = document.createElement("div"); row.className = "krow";
        row.innerHTML = '<a href="' + esc(f.url) + '" target="_blank" rel="noopener"><img src="' + esc(f.image || "") + '" alt=""></a>' +
          '<div><div class="t"><a href="' + esc(f.url) + '" target="_blank" rel="noopener">' + esc(f.title || "(no title)") + '</a></div>' +
          '<div class="m"><span class="' + (deal ? 'deal' : '') + '">' + money(f.price) + (deal ? ' deal' : '') + '</span>' +
          (f.old_price != null ? ' · was ' + money(f.old_price) : '') + ' · ' + (SRC[f.source] || esc(f.source)) +
          (f.stale ? ' · <em>may be sold</em>' : '') + '</div></div>' +
          '<button class="x" type="button" data-key="' + esc(f.key) + '">remove</button>';
        row.querySelector(".x").addEventListener("click", function () { setVerdict(f.key, "no"); render(); });
        g.appendChild(row);
      });
      host.appendChild(g);
    });
  }

  // ---------- bags ----------
  var rarityLabel = { common: "easy to find", uncommon: "takes some looking", rare: "rare" };
  function renderBags() {
    document.querySelectorAll(".bags").forEach(function (h) { h.innerHTML = ""; });
    BAGS.forEach(function (b) {
      var host = document.querySelector('.bags[data-group="' + b.group + '"]');
      if (!host) return;
      var status = bagStatus(b.id);
      var el = document.createElement("article");
      el.className = "bag";
      el.innerHTML =
        '<div class="frame"><img src="' + b.img + '" alt="' + esc(b.name) + '"></div>' +
        '<h3>' + esc(b.name) + '</h3>' +
        '<div class="meta"><span class="tag ' + b.rarity + '">' + rarityLabel[b.rarity] + '</span><span>' + esc(b.price) + '</span></div>' +
        '<p class="note">' + esc(b.style) + '</p>' +
        '<p>' + esc(b.note) + '</p>' +
        huntHTML(b.q) +
        (b.q2 ? '<p class="note" style="margin-top:4px">Also try: "' + esc(b.q2) + '"</p>' : '') +
        '<div class="status">Status <span class="seg">' +
        ["wanted", "found", "owned"].map(function (s) {
          return '<button type="button" data-s="' + s + '"' + (s === status ? ' class="on"' : '') + '>' +
            ({ wanted: "wanted", found: "found one, watching", owned: "owned" })[s] + '</button>';
        }).join("") + '</span>' +
        (status === "owned" ? '<span class="owned-note">the tracker stops watching this one</span>' : '') + '</div>';
      el.querySelectorAll(".seg button").forEach(function (btn) {
        btn.addEventListener("click", function () { if (btn.dataset.s !== bagStatus(b.id)) setBag(b.id, btn.dataset.s); });
      });
      host.appendChild(el);
    });
  }
  function renderRecs(list, group) {
    var host = document.querySelector('.recs[data-group="' + group + '"]');
    host.innerHTML = "";
    list.forEach(function (r) {
      var el = document.createElement("article");
      el.className = "rec";
      el.innerHTML = '<h3>' + esc(r.name) + '</h3><p class="why">' + esc(r.why) + '</p><p class="range">' + esc(r.range) + '</p>' + huntHTML(r.q);
      if (r.site) { var s = document.createElement("a"); s.href = r.site[1]; s.target = "_blank"; s.rel = "noopener"; s.textContent = r.site[0]; el.querySelector(".hunt").prepend(s); }
      host.appendChild(el);
    });
  }

  // ---------- tabs ----------
  function showTab(name) {
    document.querySelectorAll(".tab").forEach(function (t) { t.classList.toggle("active", t.id === "tab-" + name); });
    document.querySelectorAll(".tabs button").forEach(function (b) { b.classList.toggle("on", b.dataset.tab === name); });
    writeLS("tab", name);
    window.scrollTo(0, 0);
  }
  document.querySelectorAll(".tabs button").forEach(function (b) {
    b.addEventListener("click", function () { showTab(b.dataset.tab); });
  });

  function renderBadge() {
    var n = unreviewed().length;
    $("badge").textContent = n ? String(n) : "";
  }
  function render() { renderReview(); renderKept(); renderBadge(); }

  // ---------- load ----------
  function getJSON(name) {
    return fetch(name, { cache: "no-store" }).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; });
  }
  Promise.all([getJSON("finds.json"), getJSON("verdicts.json")]).then(function (res) {
    var fd = res[0], vd = res[1];
    if (fd && Array.isArray(fd.finds)) {
      finds = fd.finds; bagsMeta = fd.bags || {}; generated = fd.generated || null;
    } else {
      findsMissing = true;
    }
    if (vd && typeof vd === "object") {
      verdicts = { fetched: vd.fetched || null, listings: vd.listings || {}, bags: vd.bags || {} };
    }
    pruneOverlay();
    $("subline").textContent = findsMissing ? "Nine bags worth waiting for, where to find them, and what to pay."
      : (generated ? "Last checked " + when(generated) + "." : "");
    render(); renderBags(); renderRecs(RECS1, "recs1"); renderRecs(RECS2, "recs2");
    showTab(readLS("tab", "review"));
    flush();
  });
})();
</script>
</body>
</html>
```

- [ ] **Step 2: Serve it locally against a fixture and eyeball it**

```bash
mkdir -p state/probe/site && cp -r docs/. state/probe/site/
cat > state/probe/site/finds.json <<'EOF'
{"generated": "2026-09-23T02:00:00+00:00",
 "bags": {"chelsea-braided": {"name": "Brown Chelsea Optic Satchel, braided handles", "deal_price": 120},
          "patchwork-leopard-tote": {"name": "Signature Patchwork Gallery Tote, leopard patch", "deal_price": 110}},
 "finds": [
  {"key": "mercari:m1", "bag": "chelsea-braided", "title": "Y2K 10995 Chelsea Optic Signature Turn Lock Satchel - Coach", "price": 190, "old_price": null, "currency": "USD", "source": "mercari", "url": "https://www.mercari.com/us/item/m1/", "image": "img/chelsea-braided.jpg", "seller": null, "condition": null, "first_seen": "2026-09-23T01:00:00+00:00", "last_seen": "2026-09-23T02:00:00+00:00", "kind": "new", "stale": false},
  {"key": "depop:x-coach-patchwork-tote-1a2b", "bag": "patchwork-leopard-tote", "title": "coach patchwork tote bag (Coach women's multi colour bag)", "price": 40, "old_price": null, "currency": "USD", "source": "depop", "url": "https://www.depop.com/products/x-coach-patchwork-tote-1a2b/", "image": "img/patchwork-leopard-tote.jpg", "seller": "x", "condition": null, "first_seen": "2026-09-22T01:00:00+00:00", "last_seen": "2026-09-23T02:00:00+00:00", "kind": "deal", "stale": false},
  {"key": "ebay:3", "bag": "patchwork-leopard-tote", "title": "Vintage Ocelot Gray Patchwork Tote Bag - Coach", "price": 150, "old_price": 199, "currency": "USD", "source": "ebay", "url": "https://www.ebay.com/itm/3", "image": "img/patchwork-leopard-tote.jpg", "seller": "seller1", "condition": "Pre-owned", "first_seen": "2026-09-18T01:00:00+00:00", "last_seen": "2026-09-19T02:00:00+00:00", "kind": "drop", "stale": true}
 ]}
EOF
(cd state/probe/site && ../../../.venv/Scripts/python -m http.server 8000 > /dev/null 2>&1 &)
```

Open `http://localhost:8000/` in a browser at phone width (devtools, 390 px). Check: three-count badge, first card shows the Chelsea listing with her reference inset, dragging left shows the red "Not it" stamp, dragging right the green "Keep" stamp; the cross/tick buttons work; the Undo toast brings the card back; Kept tab groups by bag; Bags tab renders nine bags with the segmented control; the four folds open. The "Some verdicts haven't saved" line will show because the Worker URL isn't reachable from the fixture (or is reachable and CORS-blocked from localhost); that is expected here.

- [ ] **Step 3: Commit**

```bash
git add docs/index.html
git commit -m "Add the review page: swipe stack, kept list, bag guide"
```

---

### Task 9: Playwright test for the page

**Files:**
- Create: `tests/test_page.py`

**Interfaces:**
- Consumes: `docs/index.html` (Task 8) with `window.WORKER_URL_OVERRIDE`; fixture from Task 8 Step 2 (recreated here).

- [ ] **Step 1: Write the test**

```python
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


def test_initial_render(page):
    assert page.locator("#badge").inner_text() == "3"
    assert "Chelsea one" in page.locator(".card:not(.next) h3").inner_text()
    assert page.locator(".card:not(.next) .ref").count() == 1
    assert "Last checked" in page.locator("#subline").inner_text()


def test_swipe_left_posts_no_and_advances(page):
    _drag_top_card(page, -260)
    page.wait_for_function("document.querySelector('.card:not(.next) h3').textContent.includes('Patchwork two')")
    page.wait_for_function("window.__posts === undefined || true")
    assert page.posts[-1] == {"token": page.posts[-1]["token"], "kind": "listing", "key": "mercari:m1", "value": "no"}
    assert page.locator("#badge").inner_text() == "2"


def test_button_keep_posts_keep_and_shows_in_kept(page):
    page.click("#btn-keep")
    page.wait_for_function("document.querySelector('.card:not(.next) h3').textContent.includes('Patchwork two')")
    assert page.posts[-1]["kind"] == "listing" and page.posts[-1]["value"] == "keep" and page.posts[-1]["key"] == "mercari:m1"
    page.click(".tabs button[data-tab=kept]")
    assert "Chelsea one" in page.locator("#kept").inner_text()
    page.click("#kept .x")
    assert page.posts[-1] == {**page.posts[-1], "key": "mercari:m1", "value": "no"}


def test_undo_restores_card_and_posts_clear(page):
    page.click("#btn-no")
    page.wait_for_function("document.querySelector('.card:not(.next) h3').textContent.includes('Patchwork two')")
    page.click("#undo")
    page.wait_for_function("document.querySelector('.card:not(.next) h3').textContent.includes('Chelsea one')")
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
```

- [ ] **Step 2: Run it**

Run: `.venv/Scripts/python -m pytest tests/test_page.py -q`
Expected: `9 passed`. If `test_swipe_left_posts_no_and_advances` fails on the post assertion, the drag did not cross a third of the card width: widen `dx` to `-300`. If `test_overlay_survives_reload` fails, the overlay prune dropped the entry: check `pruneOverlay` only deletes when the server has the key with a newer-or-equal `t`.

- [ ] **Step 3: Commit**

```bash
git add tests/test_page.py
git commit -m "Playwright test for the review page at phone width"
```

---

### Task 10: Publish and wire up

This task assumes Pass 1 step 4 has happened (public repo exists, `origin` set, Actions secrets for eBay set). If not, do Pass 1 step 4 first, creating the repo **public**.

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Push and enable Pages**

```bash
git push -u origin main
OWNER=$(gh api user -q .login); REPO=$(basename "$(git rev-parse --show-toplevel)")
gh api -X POST "repos/$OWNER/$REPO/pages" -f build_type=legacy -f 'source[branch]=main' -f 'source[path]=/docs'
gh api "repos/$OWNER/$REPO/pages" -q .html_url
```

Expected: the last command prints `https://<login>.github.io/<repo>/`. The first Pages build takes a minute; `gh api "repos/$OWNER/$REPO/pages/builds/latest" -q .status` reports `built` when done.

- [ ] **Step 2: Set the secrets**

```bash
set -a; . ./.env; set +a
gh secret set VERDICT_URL --body "$VERDICT_URL"
gh secret set VERDICT_TOKEN --body "$VERDICT_TOKEN"
# email (values from Marcus): Gmail needs an app password, host smtp.gmail.com, port 587
gh secret set SMTP_HOST --body "smtp.gmail.com"
gh secret set SMTP_PORT --body "587"
gh secret set SMTP_USER --body "$SMTP_USER"
gh secret set SMTP_PASS --body "$SMTP_PASS"
gh secret set EMAIL_TO --body "$EMAIL_TO"
gh secret list
```

Expected: the list shows every name above plus `EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET` (and `DISCORD_WEBHOOK_URL` if kept).

- [ ] **Step 3: Confirm the Worker's CORS origin matches**

`worker/wrangler.toml` `ALLOWED_ORIGIN` must equal the scheme+host of the Pages URL (`https://<login>.github.io`, no path). If it doesn't, fix it and run `cd worker && npx wrangler deploy && cd ..`, then commit.

- [ ] **Step 4: First live cycle**

```bash
gh workflow run "bag tracker" -f sources=cloud -f init=true
gh run watch --exit-status
git pull --rebase
ls -la docs/finds.json state/verdicts.json
```

Expected: the run succeeds, the state commit lands, and `docs/finds.json` exists with the eBay/Poshmark matches. Open the Pages URL on a phone: cards appear. Swipe one. Then:

```bash
set -a; . ./.env; set +a
curl -s "$VERDICT_URL/v?token=$VERDICT_TOKEN"
gh workflow run "bag tracker" -f sources=cloud && gh run watch --exit-status && git pull --rebase
.venv/Scripts/python -c "import json;print(json.load(open('state/verdicts.json'))['listings'])"
.venv/Scripts/python -c "import json;print([f['key'] for f in json.load(open('docs/finds.json'))['finds']][:5])"
```

Expected: the swiped key shows in the Worker output with `"v": "no"`, then in `state/verdicts.json`, and is absent from `finds.json`. The run log shows `1 rejected skipped` on the summary line.

- [ ] **Step 5: Update the README**

Replace the "What it doesn't do (yet)" bullet about the pretty page and add a section after "Setup: home":

```markdown
## Her page

`docs/` is published with GitHub Pages (Settings → Pages → branch `main`, folder `/docs`). It reads
`docs/finds.json` (the tracker writes it every run) and `docs/verdicts.json` (pulled from the Worker
before every run). She swipes left for "not it" and right for "keep"; both go to a tiny Cloudflare
Worker in `worker/` and come back into the tracker next run, so rejected listings never re-alert and a
bag marked "owned" is no longer searched. Anything she keeps shows up in your next email.

Worker setup, once: `cd worker && npx wrangler login && npx wrangler kv namespace create VERDICTS`
(paste the id into `wrangler.toml`), `npx wrangler secret put TOKEN`, `npx wrangler deploy`. Put the
same token in the page (`TOKEN` at the top of the script in `docs/index.html`), in `.env`, and in the
`VERDICT_TOKEN` secret; the deployed URL goes in `VERDICT_URL`. `ALLOWED_ORIGIN` in `wrangler.toml`
must be your Pages origin (`https://<you>.github.io`).
```

Add `VERDICT_URL`, `VERDICT_TOKEN` and the SMTP rows to the secrets table in "Setup: cloud", and change the Windows scheduling note in "Setup: home" to mention Task Scheduler running `run_home.sh` through Git Bash every 30 minutes.

- [ ] **Step 6: Commit and push**

```bash
git add README.md
git commit -m "README: her page, the Worker, and the new secrets"
git push
```

---

## Self-review

- **Spec coverage.** finds.json rules → Task 2; verdicts file and `notified` → Tasks 1, 4; Worker routes, token, CORS, TTL, key cap → Task 6; sync script never failing → Task 4; owned-bag skip, "no" skip, finds on `--init`, kept notifications, dry-run prints kept → Task 4; notify channels → Task 3; runners committing four files → Task 5; page tabs, overlay, queue, gestures, buttons, undo, lightbox, empty/missing states, bag status control, prose folds, 400 px → Task 8; photos out of data URIs → Task 7; hosting from `/docs`, secrets, CORS origin check, end-to-end → Task 10; tests → Tasks 1, 2, 3, 6 (curl), 9. Out-of-scope items untouched.
- **Placeholders.** `REPLACE-ME` in Task 8 and `filled-in-by-step-5` / `<login>` in Task 6 are values that only exist after a deploy step; each has the step that produces them named. No TBDs.
- **Type consistency.** `verdicts.load/save/merge/owned_bags/rejected/unnotified_keeps/mark_notified` used in Task 4 as defined in Task 1. `finds.load/update/save` and the `matched` record shape (`key, bag, listing, kind, old_price, first_seen`) used in Task 4 as defined in Task 2. `notify.send(alerts, kept)` and `email_lines` as defined in Task 3. Worker request/response shapes match between Task 6, `sync_verdicts.py`, and the page's `flush()`. Bag ids in Task 7 filenames, Task 8 `BAGS`, and `config.yaml` agree.
