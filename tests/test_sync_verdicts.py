import json

import sync_verdicts


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_malformed_payload_is_ignored(tmp_path, monkeypatch):
    state_path = tmp_path / "state" / "verdicts.json"
    site_path = tmp_path / "docs" / "verdicts.json"
    monkeypatch.setattr(sync_verdicts, "STATE_PATH", str(state_path))
    monkeypatch.setattr(sync_verdicts, "SITE_PATH", str(site_path))
    monkeypatch.setenv("VERDICT_URL", "https://example.com")
    monkeypatch.setenv("VERDICT_TOKEN", "tok")

    calls = []

    def fake_get(*args, **kwargs):
        calls.append((args, kwargs))
        return _FakeResponse([1, 2])

    monkeypatch.setattr(sync_verdicts.requests, "get", fake_get)

    assert sync_verdicts.main() == 0
    assert len(calls) == 1
    assert not state_path.exists()
    assert not site_path.exists()


def test_good_payload_writes_both_files(tmp_path, monkeypatch):
    state_path = tmp_path / "state" / "verdicts.json"
    site_path = tmp_path / "docs" / "verdicts.json"
    monkeypatch.setattr(sync_verdicts, "STATE_PATH", str(state_path))
    monkeypatch.setattr(sync_verdicts, "SITE_PATH", str(site_path))
    monkeypatch.setenv("VERDICT_URL", "https://example.com")
    monkeypatch.setenv("VERDICT_TOKEN", "secret-token")

    payload = {"listings": {"a:1": {"v": "no", "t": "1"}}, "bags": {}}
    calls = []

    def fake_get(*args, **kwargs):
        calls.append((args, kwargs))
        return _FakeResponse(payload)

    monkeypatch.setattr(sync_verdicts.requests, "get", fake_get)

    assert sync_verdicts.main() == 0

    assert len(calls) == 1
    _, kwargs = calls[0]
    assert kwargs.get("headers") == {"Authorization": "Bearer secret-token"}
    assert "params" not in kwargs

    for p in (state_path, site_path):
        d = json.loads(p.read_text(encoding="utf-8"))
        assert d["listings"]["a:1"]["v"] == "no"


def test_missing_env_skips_without_calling_requests(tmp_path, monkeypatch):
    state_path = tmp_path / "state" / "verdicts.json"
    site_path = tmp_path / "docs" / "verdicts.json"
    monkeypatch.setattr(sync_verdicts, "STATE_PATH", str(state_path))
    monkeypatch.setattr(sync_verdicts, "SITE_PATH", str(site_path))
    monkeypatch.delenv("VERDICT_URL", raising=False)
    monkeypatch.delenv("VERDICT_TOKEN", raising=False)

    calls = []
    monkeypatch.setattr(sync_verdicts.requests, "get", lambda *a, **k: calls.append((a, k)))

    assert sync_verdicts.main() == 0
    assert calls == []
