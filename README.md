# Bag tracker

Watches eBay, Poshmark, Depop and Mercari for nine specific vintage Coach bags and posts new listings, deals and price drops to a shared Discord channel. Free to run: nothing here costs money unless you opt into the paid fallback at the bottom.

## How it works

Two runners share one repo and one `state/seen.json`:

- **Cloud (GitHub Actions, every 20 min):** eBay via its official free API, and Poshmark by reading the JSON embedded in its search page. Both work from GitHub's servers.
- **Home (your laptop / old machine / Pi, every 30 min):** Depop and Mercari. Both refuse datacenter IPs, so they run from a home connection, and both need a headless browser (Playwright), which the script drives; Depop's plain web API now rejects non-browser requests even from home.

Every listing title is matched against per-bag rules in `config.yaml` (must-have term groups, exclusions, a max price and a "deal" price). New matches go to Discord as embeds with the photo, price, source and seller; deals get a red embed; a listing you've already seen that drops 15% re-alerts as a price drop. State is committed back after each run so nothing repeats.

You can run cloud-only and skip the home machine entirely. You'll still get eBay and Poshmark, which is most of the supply for these bags; use Gem's own push alerts on your phone for Depop and Mercari.

## Setup: cloud (20 minutes)

1. **Repo.** New private GitHub repo, push this folder. Settings → Actions → General → Workflow permissions → *Read and write*.
2. **eBay keys.** developer.ebay.com → sign in → *Application Keys* → create a **Production** keyset. Copy App ID and Cert ID. Free; this uses ~1,200 of the 5,000 daily calls.
3. **Discord.** Server → channel `#bag-alerts` → Integrations → Webhooks → New → copy URL. Invite her. Both of you mute everything but this channel.
4. **Secrets.** Repo → Settings → Secrets and variables → Actions:

   | Secret | Value |
   |---|---|
   | `EBAY_CLIENT_ID` | eBay App ID |
   | `EBAY_CLIENT_SECRET` | eBay Cert ID |
   | `DISCORD_WEBHOOK_URL` | webhook URL |

   Other channels, optional, all can be on at once: `NTFY_TOPIC`; `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`; `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `EMAIL_TO`.
5. **Seed it.** Actions → *bag tracker* → *Run workflow* → sources `cloud`, init `true`. Records what's currently listed without sending 200 alerts.
6. **Watch a real run.** Actions → next scheduled run → log shows one line per query with a count, then one line per alert.

## Setup: home (15 minutes, optional)

On the machine that will run Depop and Mercari:

    git clone <your repo> ~/bag-tracker && cd ~/bag-tracker
    pip3 install -r requirements.txt playwright
    playwright install chromium
    echo 'DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...' > .env
    python3 tracker.py --probe depop      # should print a few product cards; saves a screenshot to state/probe/
    python3 tracker.py --probe mercari    # should print a few items; saves a screenshot to state/probe/
    python3 tracker.py --sources home --init
    python3 tracker.py --sources home --dry-run

Then schedule it. macOS/Linux `crontab -e`:

    */30 * * * * /Users/you/bag-tracker/run_home.sh >> /Users/you/bag-tracker/state/home.log 2>&1

The machine needs to be awake for the cron to fire (on a Mac: System Settings → Energy → prevent sleep, or use `caffeinate`). A Raspberry Pi on the router is the fire-and-forget version.

**If a probe fails at home:** Depop returning 0 items with a "Forbidden" screenshot means the User-Agent in `depop.py` needs refreshing to a current Chrome string. Mercari returning 0 items with a "Just a moment" screenshot means Cloudflare is challenging the browser; `mercari.py` needs the locally installed Google Chrome (it falls back to Playwright's Chromium, which gets challenged). Install Chrome, or fall back to Apify for that one site.

## Tuning

- **Too noisy?** Add words to that bag's `exclude` list or lower `max_price`. Titles are matched lowercase; style numbers match as whole tokens.
- **Missing things?** Loosen a `must` group (add synonyms sellers use) or add an `ebay_queries` line (those run on Poshmark too). `python tracker.py --sources poshmark --dry-run` shows what a change catches, live, without sending anything.
- **Depop/Mercari queries** come from `sweep_queries` plus each bag's `extra_queries`. Keep them short; those sources are browser-slow.
- **Scraping etiquette.** The defaults are gentle (a few dozen page loads an hour, spaced out). Don't crank the cadence; getting an IP blocked is the only real risk here.

## Paid fallback (Apify)

If you'd rather not keep a home machine on, or one site starts blocking you, `sources/apify_actor.py` uses a hosted scraper for Depop and Mercari (about $3 per 1,000 results). Add `APIFY_TOKEN` as a secret and the workflow's second cron line starts running it three times a day. With the default queries that's roughly $25–50/month. Without the token it does nothing.

## What it doesn't do (yet)

- Auction end-time reminders for eBay.
- Authentication: it can't spot a fake. The pre-purchase checklist on the hunting-guide page still applies.
- The pretty page: this repo could write a `finds.json` and republish the guide with a live "recent finds" slide. Second pass.
