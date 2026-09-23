# Finds review page: design

Date: 2026-09-23. Status: approved in conversation, pending written review.

## Goal

Replace the static slideshow with a phone-first page where she reviews the tracker's
matches one card at a time (swipe left "not it", swipe right "keep"), keeps a shortlist, and
still has the bag guide. Her verdicts flow back to the tracker so rejected listings never
re-alert and owned bags stop being searched. Marcus gets email (and optionally Discord) with
new finds plus anything she kept since the last run.

Constraints carried over: nothing costs money; no cadence increase; matching rules only
tighten; `.env` never committed; one HTML file plus JSON, no build step, no framework.

## Architecture

```
tracker.py (Actions every 20 min: eBay+Poshmark; home every 30 min: Depop+Mercari)
   reads  state/seen.json, state/verdicts.json, config.yaml
   writes state/seen.json, docs/finds.json            -> committed by the runner
sync_verdicts.py (runs before tracker in both runners)
   GET  worker /v                                     -> state/verdicts.json, docs/verdicts.json
docs/index.html (GitHub Pages, /docs folder on main)
   fetch finds.json + verdicts.json (same origin)
   POST worker /v on every swipe / bag status change
worker/ (Cloudflare Worker + KV, free tier)
   POST /v  store or clear one verdict     GET /v  list all
```

## Data

### `docs/finds.json` (written by tracker after every run, including `--init`)

```json
{
  "generated": "2026-09-23T02:00:00Z",
  "bags": {"chelsea-braided": {"name": "Brown Chelsea Optic Satchel, braided handles", "deal_price": 120}},
  "finds": [
    {"key": "mercari:m16817299308", "bag": "chelsea-braided", "title": "...", "price": 190,
     "old_price": null, "currency": "USD", "source": "mercari", "url": "...", "image": "...",
     "seller": null, "condition": null, "first_seen": "...", "last_seen": "...",
     "kind": "new", "stale": false}
  ]
}
```

- Contains every listing that matched a bag, whether or not it alerted.
- Rules, applied on every write: drop listings with a "no" verdict; drop listings whose
  `first_seen` is older than 14 days; `stale = last_seen` older than 3 days; sort newest
  `first_seen` first; keep the first 40.
- `kind` is the alert kind at first sight, upgraded to `drop`/`deal` when a price drop
  alerts. `old_price` is set only on a drop.
- `bags` is every bag in `config.yaml` that is not owned, so the page never needs to know
  config internals beyond ids.

### `state/verdicts.json` and `docs/verdicts.json` (identical; written by `sync_verdicts.py`)

```json
{
  "fetched": "2026-09-23T02:00:00Z",
  "listings": {"mercari:m16817299308": {"v": "no", "t": "2026-09-23T01:00:00Z", "notified": false}},
  "bags": {"chelsea-braided": {"status": "owned", "t": "2026-09-23T01:00:00Z"}}
}
```

- `v` is `no` or `keep`. `status` is `wanted`, `found` or `owned`.
- `notified` is set true by the tracker after a keep has been included in a notification.
  The tracker writes it back to both copies.
- Only listing keys present in `state/seen.json` and bag ids present in `config.yaml` are
  honoured; anything else is ignored on read (never deleted from the Worker, just ignored).

### Worker API

- `POST /v` JSON body `{"token": "...", "kind": "listing"|"bag", "key": "...", "value": "no"|"keep"|"clear"|"wanted"|"found"|"owned"}`.
  Stores `l:<key>` or `b:<key>` -> `{"v"|"status", "t"}` with a 60-day expiry; `clear` deletes.
  Returns 204. Wrong token: 401. Malformed: 400. Keys are capped at 200 chars.
- `GET /v` with header `Authorization: Bearer <token>` returns the two maps above (without `notified`). Missing or wrong token: 401. The token is never placed in a URL, so it stays out of request logs.
- CORS: `Access-Control-Allow-Origin` is exactly the Pages origin; preflight handled.
- Token is a random 32-byte hex string generated once. It lives in the page source, in
  `.env`, and in the Actions secrets. Its job is to stop drive-by writes, not determined ones;
  the tracker-side key validation is the real guard.

## Tracker changes

- `sync_verdicts.py`: reads `VERDICT_URL` and `VERDICT_TOKEN`; if either is missing, prints
  one line and exits 0. On success writes both verdict files. On HTTP or network failure
  prints the error and exits 0, leaving the previous files in place.
- `tracker.py`:
  - loads verdicts; bags with status `owned` are removed from the working bag list before
    any collector runs, so their queries are never issued.
  - a listing whose key has verdict `no` is skipped before classification: no alert, no
    price-drop alert, not in finds.
  - after the alert loop, `finds.update(...)` merges every matched listing into
    `docs/finds.json` under the rules above. Runs on `--init` too. Not on `--dry-run`.
  - keep verdicts with `notified == false` whose key is in seen state are gathered as
    `kept` entries (with title, price, url, source, bag from seen state / finds) and passed
    to `notify.send(alerts, kept)`; after a successful send they are marked notified and
    both verdict files rewritten. If there are no alerts and no new keeps, nothing is sent.
  - `--dry-run` prints the kept section too, sends nothing, writes nothing.
- `notify.py`: `send(alerts, kept=None)`. Email gets a "She kept" block after the alerts.
  Discord gets one extra embed per kept listing with a distinct colour. ntfy/Telegram
  unchanged apart from the signature.
- `run_home.sh` and `track.yml`: run `sync_verdicts.py` before `tracker.py`; commit
  `state/seen.json state/verdicts.json docs/finds.json docs/verdicts.json`.
- `state/seen.json` gains nothing new. `seen.json` stays the dedupe authority.

## Page (`docs/index.html`, `docs/img/*.jpg`)

- Vanilla JS, one file, Google Fonts as today, existing tokens (`--bg`, `--cream`,
  `--cocoa`, `--lace`, `--rule`, tag colours, Cormorant Garamond + EB Garamond).
- Reference photos extracted from the data URIs into `docs/img/<bag-id>.jpg`.
- Constants at the top of the script: `WORKER_URL`, `TOKEN`, and the `BAGS` array (id
  aligned to `config.yaml`, plus name, style, rarity, price range, note, two search queries).
- Load: fetch `finds.json` and `verdicts.json` with `cache: "no-store"`. Local overlay in
  `localStorage`: `{key: {v, t}}` for swipes made in this browser; an overlay entry is
  dropped once `verdicts.json` contains the same key with `t >= overlay.t`. Unsent queue in
  `localStorage`, flushed on load and after each new swipe.
- Tabs (sticky bottom bar): Review (badge = unreviewed count), Kept, Bags.
- Review card: listing photo (3:4, cover), reference inset bottom-left (tap to enlarge),
  price chip (deal style when `kind == deal` or `price <= bags[bag].deal_price`), source
  label, title, seller/condition line, "may be sold" marker when stale, "was $X" on drops.
  Tap photo opens `url` in a new tab. Pointer-event drag: commit past 33% of width or a
  fast flick; tilt while dragging; cross/tick buttons under the card. Undo toast 5 s.
  Empty state shows `generated` as "last checked". Missing finds.json: "The tracker hasn't
  run yet."
- Kept: grouped by bag in `bags` order; rows show thumbnail, title, price (+ was), source,
  stale marker, link, remove (posts `no`).
- Bags: cards in her page's current order and wording, wanted/found/owned segmented control
  (posts bag verdict; owned bags show a note that the tracker stops watching them).
  Collapsible sections below: Where to hunt, Before you buy, Beyond Coach, Three things,
  ported verbatim.
- Works at 400 px; no horizontal page scroll; no swipe navigation between tabs.

## Hosting and deployment

- Public GitHub repo (Pages on the free plan needs public). Nothing secret is in the repo.
- Pages source: branch `main`, folder `/docs`. No deploy workflow.
- Worker: `worker/wrangler.toml` and `worker/src/index.js` in the repo. Deployed with
  `npx wrangler` after a one-time interactive `wrangler login` that Marcus runs. KV
  namespace created once with wrangler; its id goes in `wrangler.toml`. Token set as a
  Worker secret with `wrangler secret put`.
- Actions secrets: `EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET`, `VERDICT_URL`, `VERDICT_TOKEN`,
  `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `EMAIL_TO`, optionally
  `DISCORD_WEBHOOK_URL`. Same names in the local `.env`.

## Testing

- `tests/test_finds.py`: merge, prune at 14 days, stale at 3 days, cap 40, "no" removal,
  drop upgrade. `tests/test_verdicts.py`: owned-bag skip, "no" skip, keep gathering and
  notified flag, unknown keys ignored. Run with pytest inside `.venv`.
- Worker: `wrangler dev` locally with curl for POST/GET/clear/bad token; repeat live.
- Page: `python -m http.server` in `docs/` with a fixture `finds.json`; Playwright at a
  390x844 viewport driving pointer events for both swipes and asserting the POST bodies;
  then the live Pages URL on her phone.
- End to end: swipe on phone -> visible in `GET /v` -> next workflow run writes
  `verdicts.json` -> listing gone from `finds.json` -> re-run of both runners produces no
  repeat alert.

## Out of scope

Per-user verdicts, auth beyond the shared token, auto-tuning of matching rules from
verdicts (the rejected titles are there for a human to read), auction reminders.
