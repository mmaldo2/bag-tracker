"""tracker.main() end to end with the collectors and notifier faked out.

Covers the wiring the other unit tests don't: owned bags dropping out of the search,
rejected listings never alerting or reaching finds.json, kept listings being gathered
and marked notified, and what --dry-run / --init do and don't write.
"""
import json
import os
import sys
from datetime import datetime, timezone

import yaml

import notify
import tracker

CHELSEA_TITLE = "Coach Chelsea optic braided satchel brown"
CHELSEA_NAME = "Brown Chelsea Optic Satchel, braided handles"


def _config_bag_ids():
    with open(os.path.join(tracker.ROOT, "config.yaml"), encoding="utf-8") as f:
        return [b["id"] for b in yaml.safe_load(f)["bags"]]


def _listing(source, id, title, price):
    return {"source": source, "id": id, "title": title, "price": price, "currency": "USD",
            "url": f"https://x/{id}", "image": None, "condition": None, "seller": None,
            "created": None, "buying": "fixed"}


def _verdicts(listings=None, bags=None):
    return {"fetched": "2026-09-23T00:00:00+00:00", "listings": listings or {}, "bags": bags or {}}


def _find_record(key, bag, first_seen):
    return {"key": key, "bag": bag, "title": CHELSEA_TITLE, "price": 180, "old_price": None,
            "currency": "USD", "source": key.split(":")[0], "url": "https://x/" + key,
            "image": None, "seller": None, "condition": None, "first_seen": first_seen,
            "last_seen": first_seen, "kind": "new", "stale": False}


def run(monkeypatch, tmp_path, argv, listings, verdicts=None, finds=None):
    monkeypatch.setattr(tracker, "STATE", str(tmp_path / "seen.json"))
    monkeypatch.setattr(tracker, "FINDS", str(tmp_path / "docs" / "finds.json"))
    monkeypatch.setattr(tracker, "VERDICTS", str(tmp_path / "verdicts.json"))
    monkeypatch.setattr(tracker, "VERDICTS_SITE", str(tmp_path / "docs" / "verdicts.json"))
    if verdicts is not None:
        (tmp_path / "verdicts.json").write_text(json.dumps(verdicts), encoding="utf-8")
    if finds is not None:
        (tmp_path / "docs").mkdir(exist_ok=True)
        (tmp_path / "docs" / "finds.json").write_text(
            json.dumps({"generated": "2026-09-23T00:00:00+00:00", "bags": {}, "finds": finds}), encoding="utf-8")
    seen_bags = []

    def fake_collect(cfg, bags, log):
        seen_bags.append([b["id"] for b in bags])
        return listings

    monkeypatch.setattr(tracker, "collect_depop", fake_collect)
    monkeypatch.setattr(tracker, "collect_mercari", lambda cfg, bags, log: [])
    sent = []
    monkeypatch.setattr(notify, "send", lambda alerts, kept=None: sent.append((alerts, kept or [])) or ["fake"])
    monkeypatch.setattr(sys, "argv", ["tracker.py", "--sources", "home"] + argv)
    tracker.main()
    return seen_bags, sent


def _finds_on_disk(tmp_path):
    p = tmp_path / "docs" / "finds.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))["finds"]


def test_owned_bag_is_not_searched_and_never_alerts(monkeypatch, tmp_path):
    seen_bags, sent = run(
        monkeypatch, tmp_path, [],
        [_listing("depop", "d1", CHELSEA_TITLE, 180)],
        verdicts=_verdicts(bags={"chelsea-braided": {"status": "owned", "t": "1"}}))
    assert "chelsea-braided" not in seen_bags[0]
    assert set(seen_bags[0]) == set(_config_bag_ids()) - {"chelsea-braided"}
    alerts, kept = sent[0]
    assert alerts == [] and kept == []
    assert [f["key"] for f in _finds_on_disk(tmp_path)] == []


def test_rejected_listing_is_skipped_but_its_neighbour_is_not(monkeypatch, tmp_path):
    _, sent = run(
        monkeypatch, tmp_path, [],
        [_listing("depop", "d1", CHELSEA_TITLE, 180), _listing("depop", "d2", CHELSEA_TITLE, 170)],
        verdicts=_verdicts(listings={"depop:d1": {"v": "no", "t": "1", "notified": False}}))
    alerts, kept = sent[0]
    assert [a["id"] for a in alerts] == ["d2"]
    assert kept == []
    assert [f["key"] for f in _finds_on_disk(tmp_path)] == ["depop:d2"]


def test_kept_listing_is_gathered_and_marked_notified(monkeypatch, tmp_path):
    now = datetime.now(timezone.utc).isoformat()
    _, sent = run(
        monkeypatch, tmp_path, [], [],
        verdicts=_verdicts(listings={"depop:d9": {"v": "keep", "t": "1", "notified": False}}),
        finds=[_find_record("depop:d9", "chelsea-braided", now)])
    alerts, kept = sent[0]
    assert alerts == []
    assert len(kept) == 1
    assert kept[0]["kind"] == "kept"
    assert kept[0]["bag"] == CHELSEA_NAME
    assert kept[0]["bag_id"] == "chelsea-braided"
    for p in (tmp_path / "verdicts.json", tmp_path / "docs" / "verdicts.json"):
        saved = json.loads(p.read_text(encoding="utf-8"))
        assert saved["listings"]["depop:d9"]["notified"] is True


def test_unknown_verdict_keys_are_ignored(monkeypatch, tmp_path):
    seen_bags, sent = run(
        monkeypatch, tmp_path, [],
        [_listing("depop", "d3", CHELSEA_TITLE, 180)],
        verdicts=_verdicts(listings={"depop:never-seen": {"v": "no", "t": "1", "notified": False}},
                           bags={"not-a-real-bag": {"status": "owned", "t": "1"}}))
    assert seen_bags[0] == _config_bag_ids()          # no bag removed
    alerts, kept = sent[0]
    assert [a["id"] for a in alerts] == ["d3"]        # the real listing still alerts
    assert kept == []
    assert [f["key"] for f in _finds_on_disk(tmp_path)] == ["depop:d3"]


def test_dry_run_sends_nothing_and_writes_nothing(monkeypatch, tmp_path):
    _, sent = run(monkeypatch, tmp_path, ["--dry-run"], [_listing("depop", "d4", CHELSEA_TITLE, 180)])
    assert sent == []
    assert not (tmp_path / "seen.json").exists()
    assert not (tmp_path / "docs" / "finds.json").exists()


def test_init_writes_state_and_finds_but_sends_nothing(monkeypatch, tmp_path):
    _, sent = run(monkeypatch, tmp_path, ["--init"], [_listing("depop", "d5", CHELSEA_TITLE, 180)])
    assert sent == []
    state = json.loads((tmp_path / "seen.json").read_text(encoding="utf-8"))
    assert list(state) == ["depop:d5"]
    assert [f["key"] for f in _finds_on_disk(tmp_path)] == ["depop:d5"]
