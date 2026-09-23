"""Send alerts.  Every channel with its env vars set is used; nothing else is.

  Discord   DISCORD_WEBHOOK_URL
  ntfy      NTFY_TOPIC            (optional NTFY_SERVER, default https://ntfy.sh)
  Telegram  TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID
  Email     SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, EMAIL_TO  (Gmail: smtp.gmail.com, 587, app password)
"""
import os
import smtplib
import requests
from email.mime.text import MIMEText

SOURCE_LABEL = {"ebay": "eBay", "poshmark": "Poshmark", "mercari": "Mercari", "depop": "Depop"}


def _fmt_price(a):
    if a.get("price") is None:
        return "price not listed"
    cur = a.get("currency") or "USD"
    return f"${a['price']:.0f}" if cur == "USD" else f"{a['price']:.0f} {cur}"


def _headline(a):
    kind = {"new": "New listing", "deal": "DEAL", "drop": "Price drop"}[a["kind"]]
    return f"{kind}: {a['bag']}"


def _body_line(a):
    bits = [_fmt_price(a), SOURCE_LABEL.get(a["source"], a["source"])]
    if a.get("condition"):
        bits.append(a["condition"])
    if a.get("seller"):
        bits.append(f"seller {a['seller']}")
    if a["kind"] == "drop" and a.get("old_price") is not None:
        bits.insert(1, f"was ${a['old_price']:.0f}")
    return " · ".join(bits)


# ---------- Discord ----------
def discord(alerts):
    url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not url:
        return False
    colors = {"new": 0xE9A7AC, "deal": 0xC0392B, "drop": 0xD98F96}
    for i in range(0, len(alerts), 10):  # Discord allows 10 embeds per message
        embeds = []
        for a in alerts[i:i + 10]:
            e = {
                "title": (a["title"] or a["bag"])[:250],
                "url": a["url"],
                "description": _body_line(a),
                "color": colors[a["kind"]],
                "author": {"name": _headline(a)},
            }
            if a.get("image"):
                e["thumbnail"] = {"url": a["image"]}
            embeds.append(e)
        content = "💸 **Deal alert**" if any(a["kind"] == "deal" for a in alerts[i:i + 10]) else "🍒 New finds"
        r = requests.post(url, json={"content": content, "embeds": embeds}, timeout=30)
        r.raise_for_status()
    return True


# ---------- ntfy ----------
def ntfy(alerts):
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        return False
    server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    for a in alerts:
        headers = {
            "Title": _headline(a).encode("utf-8"),
            "Click": a["url"] or "",
            "Tags": "cherries" if a["kind"] != "deal" else "moneybag,cherries",
            "Priority": "high" if a["kind"] == "deal" else "default",
        }
        if a.get("image"):
            headers["Attach"] = a["image"]
        body = f"{a['title']}\n{_body_line(a)}"
        requests.post(f"{server}/{topic}", data=body.encode("utf-8"), headers=headers, timeout=30).raise_for_status()
    return True


# ---------- Telegram ----------
def telegram(alerts):
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        return False
    for a in alerts:
        text = f"<b>{_headline(a)}</b>\n{a['title']}\n{_body_line(a)}\n{a['url']}"
        if a.get("image"):
            r = requests.post(f"https://api.telegram.org/bot{tok}/sendPhoto",
                              json={"chat_id": chat, "photo": a["image"], "caption": text, "parse_mode": "HTML"}, timeout=30)
        else:
            r = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                              json={"chat_id": chat, "text": text, "parse_mode": "HTML"}, timeout=30)
        r.raise_for_status()
    return True


# ---------- Email ----------
def email(alerts):
    host = os.environ.get("SMTP_HOST")
    to = os.environ.get("EMAIL_TO")
    if not host or not to:
        return False
    lines = []
    for a in alerts:
        lines.append(f"{_headline(a)}\n{a['title']}\n{_body_line(a)}\n{a['url']}\n")
    msg = MIMEText("\n".join(lines))
    deals = sum(1 for a in alerts if a["kind"] == "deal")
    msg["Subject"] = f"Bag tracker: {len(alerts)} new" + (f", {deals} deal" if deals else "")
    msg["From"] = os.environ.get("SMTP_USER", "bag-tracker")
    msg["To"] = to
    with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", "587"))) as s:
        s.starttls()
        if os.environ.get("SMTP_USER"):
            s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
        s.sendmail(msg["From"], [x.strip() for x in to.split(",")], msg.as_string())
    return True


def send(alerts):
    """Fan out to every configured channel. Returns the list of channels that sent."""
    if not alerts:
        return []
    sent = []
    for name, fn in (("discord", discord), ("ntfy", ntfy), ("telegram", telegram), ("email", email)):
        try:
            if fn(alerts):
                sent.append(name)
        except Exception as e:  # one channel failing must not block the others
            print(f"[notify] {name} failed: {e}")
    return sent
