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


def test_kept_listings_survive_prune_and_cap():
    old_first = (NOW - timedelta(days=30)).isoformat()
    kept_old = {"key": "poshmark:kept", "bag": "b", "kind": "new", "old_price": None,
                "first_seen": old_first, "last_seen": old_first}
    matched = [M(key=f"e:{i}", first_seen=(NOW - timedelta(minutes=i)).isoformat()) for i in range(45)]
    out = F.update([kept_old], matched, set(), NOW, kept={"poshmark:kept"})
    keys = [r["key"] for r in out]
    assert "poshmark:kept" in keys and len(out) == F.MAX
    assert next(r for r in out if r["key"] == "poshmark:kept")["stale"] is True
    # without the keep verdict the same old record is pruned
    assert "poshmark:kept" not in [r["key"] for r in F.update([kept_old], matched, set(), NOW)]
