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
