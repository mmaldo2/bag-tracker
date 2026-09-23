"""The jsonstate merge driver: both runners' state files union instead of conflicting."""
import json

import merge_state


def _run(tmp_path, ours, theirs, base=None):
    """Drive main() the way git does: three real files, merged result lands in 'ours'."""
    o = tmp_path / "ours.json"
    t = tmp_path / "theirs.json"
    b = tmp_path / "base.json"
    o.write_text(json.dumps(ours), encoding="utf-8")
    t.write_text(json.dumps(theirs), encoding="utf-8")
    b.write_text(json.dumps(base if base is not None else {}), encoding="utf-8")
    rc = merge_state.main(str(b), str(o), str(t))
    return rc, json.loads(o.read_text(encoding="utf-8"))


# ---------- seen.json ----------
def test_seen_unions_and_keeps_oldest_first_seen(tmp_path):
    ours = {
        "depop:d1": {"bag": "chelsea-braided", "price": 180, "first_seen": "2026-09-20T00:00:00+00:00",
                     "last_seen": "2026-09-23T05:00:00+00:00", "title": "ours"},
        "depop:only-ours": {"bag": "x", "first_seen": "2026-09-21T00:00:00+00:00",
                            "last_seen": "2026-09-21T00:00:00+00:00"},
    }
    theirs = {
        "depop:d1": {"bag": "chelsea-braided", "price": 190, "first_seen": "2026-09-18T00:00:00+00:00",
                     "last_seen": "2026-09-23T01:00:00+00:00", "title": "theirs"},
        "ebay:only-theirs": {"bag": "y", "first_seen": "2026-09-22T00:00:00+00:00",
                             "last_seen": "2026-09-22T00:00:00+00:00"},
    }
    rc, out = _run(tmp_path, ours, theirs)
    assert rc == 0
    assert set(out) == {"depop:d1", "depop:only-ours", "ebay:only-theirs"}
    # newer last_seen (ours) wins the body...
    assert out["depop:d1"]["title"] == "ours"
    assert out["depop:d1"]["price"] == 180
    assert out["depop:d1"]["last_seen"] == "2026-09-23T05:00:00+00:00"
    # ...but first_seen keeps the older value, from theirs
    assert out["depop:d1"]["first_seen"] == "2026-09-18T00:00:00+00:00"


def test_seen_newer_side_may_be_theirs(tmp_path):
    ours = {"k": {"first_seen": "2026-09-19T00:00:00+00:00", "last_seen": "2026-09-20T00:00:00+00:00", "title": "ours"}}
    theirs = {"k": {"first_seen": "2026-09-21T00:00:00+00:00", "last_seen": "2026-09-22T00:00:00+00:00", "title": "theirs"}}
    _, out = _run(tmp_path, ours, theirs)
    assert out["k"]["title"] == "theirs"
    assert out["k"]["first_seen"] == "2026-09-19T00:00:00+00:00"


# ---------- verdicts.json ----------
def test_verdicts_union_newer_t_wins_and_notified_ors(tmp_path):
    ours = {
        "fetched": "2026-09-23T05:00:00+00:00",
        "listings": {
            "depop:same": {"v": "keep", "t": "2026-09-23T04:00:00+00:00", "notified": False},
            "depop:flip": {"v": "no", "t": "2026-09-23T04:00:00+00:00", "notified": False},
            "depop:ours-only": {"v": "keep", "t": "2026-09-23T03:00:00+00:00", "notified": True},
        },
        "bags": {"chelsea-braided": {"status": "owned", "t": "2026-09-23T04:00:00+00:00"}},
    }
    theirs = {
        "fetched": "2026-09-23T02:00:00+00:00",
        "listings": {
            "depop:same": {"v": "keep", "t": "2026-09-23T01:00:00+00:00", "notified": True},
            "depop:flip": {"v": "keep", "t": "2026-09-23T01:00:00+00:00", "notified": True},
            "ebay:theirs-only": {"v": "no", "t": "2026-09-23T01:00:00+00:00", "notified": False},
        },
        "bags": {"patchwork-leopard-tote": {"status": "wanted", "t": "2026-09-23T01:00:00+00:00"}},
    }
    rc, out = _run(tmp_path, ours, theirs)
    assert rc == 0
    assert out["fetched"] == "2026-09-23T05:00:00+00:00"          # max
    assert set(out["listings"]) == {"depop:same", "depop:flip", "depop:ours-only", "ebay:theirs-only"}
    # same verdict on both sides: newer t wins, notified is an OR
    assert out["listings"]["depop:same"]["t"] == "2026-09-23T04:00:00+00:00"
    assert out["listings"]["depop:same"]["notified"] is True
    # verdict differs: the newer side wins outright, including its notified=False
    assert out["listings"]["depop:flip"]["v"] == "no"
    assert out["listings"]["depop:flip"]["notified"] is False
    assert set(out["bags"]) == {"chelsea-braided", "patchwork-leopard-tote"}
    assert out["bags"]["chelsea-braided"]["status"] == "owned"


# ---------- finds.json ----------
def _find(key, first, last, title="t"):
    return {"key": key, "bag": "chelsea-braided", "title": title, "price": 100, "old_price": None,
            "currency": "USD", "source": "depop", "url": "https://x/" + key, "image": None,
            "seller": None, "condition": None, "first_seen": first, "last_seen": last,
            "kind": "new", "stale": False}


def test_finds_union_dedupes_sorts_and_caps(tmp_path):
    shared_ours = _find("depop:shared", "2026-09-20T00:00:00+00:00", "2026-09-23T06:00:00+00:00", "ours")
    shared_theirs = _find("depop:shared", "2026-09-17T00:00:00+00:00", "2026-09-23T02:00:00+00:00", "theirs")
    ours = {
        "generated": "2026-09-23T06:00:00+00:00",
        "bags": {"chelsea-braided": {"name": "Chelsea (ours)", "deal_price": 120}},
        "finds": [shared_ours] + [_find(f"depop:o{i}", f"2026-09-{10 + i:02d}T00:00:00+00:00",
                                        "2026-09-23T06:00:00+00:00") for i in range(30)],
    }
    theirs = {
        "generated": "2026-09-23T02:00:00+00:00",
        "bags": {"chelsea-braided": {"name": "Chelsea (theirs)", "deal_price": 120}},
        "finds": [shared_theirs] + [_find(f"ebay:t{i}", f"2026-08-{10 + i:02d}T00:00:00+00:00",
                                          "2026-09-23T02:00:00+00:00") for i in range(30)],
    }
    rc, out = _run(tmp_path, ours, theirs)
    assert rc == 0
    assert out["generated"] == "2026-09-23T06:00:00+00:00"            # max
    assert out["bags"]["chelsea-braided"]["name"] == "Chelsea (ours)"  # newer generated side
    keys = [f["key"] for f in out["finds"]]
    assert len(keys) == 40                                            # capped
    assert len(set(keys)) == 40                                       # deduped by key
    firsts = [f.get("first_seen") or "" for f in out["finds"]]
    assert firsts == sorted(firsts, reverse=True)                     # newest first
    shared = [f for f in out["finds"] if f["key"] == "depop:shared"][0]
    assert shared["title"] == "ours"                                  # newer last_seen wins
    assert shared["first_seen"] == "2026-09-17T00:00:00+00:00"        # older first_seen kept


def test_finds_keeps_both_sides_new_records(tmp_path):
    ours = {"generated": "2026-09-23T06:00:00+00:00", "bags": {},
            "finds": [_find("depop:a", "2026-09-22T00:00:00+00:00", "2026-09-23T06:00:00+00:00")]}
    theirs = {"generated": "2026-09-23T02:00:00+00:00", "bags": {},
              "finds": [_find("ebay:b", "2026-09-21T00:00:00+00:00", "2026-09-23T02:00:00+00:00")]}
    _, out = _run(tmp_path, ours, theirs)
    assert [f["key"] for f in out["finds"]] == ["depop:a", "ebay:b"]


# ---------- never wedge ----------
def test_unparseable_theirs_leaves_ours_untouched(tmp_path):
    o = tmp_path / "ours.json"
    t = tmp_path / "theirs.json"
    b = tmp_path / "base.json"
    original = json.dumps({"depop:d1": {"first_seen": "1", "last_seen": "2"}})
    o.write_text(original, encoding="utf-8")
    t.write_text("{not json at all", encoding="utf-8")
    b.write_text("{}", encoding="utf-8")
    assert merge_state.main(str(b), str(o), str(t)) == 0
    assert o.read_text(encoding="utf-8") == original
