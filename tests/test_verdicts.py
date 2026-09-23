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
