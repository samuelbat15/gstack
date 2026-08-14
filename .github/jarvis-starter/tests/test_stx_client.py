from __future__ import annotations

import json

import stx_client


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestCheckStatus:
    def test_returns_parsed_json(self, monkeypatch):
        monkeypatch.setattr(
            "urllib.request.urlopen",
            lambda request, timeout: FakeResponse({"status": "online", "vault_files": 40, "model": "mistral"}),
        )
        result = stx_client.check_status()
        assert result == {"status": "online", "vault_files": 40, "model": "mistral"}

    def test_uses_short_timeout(self, monkeypatch):
        captured = {}

        def fake_urlopen(request, timeout):
            captured["timeout"] = timeout
            return FakeResponse({"status": "online"})

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        stx_client.check_status()
        assert captured["timeout"] <= 5

    def test_hits_health_endpoint_only_never_do(self, monkeypatch):
        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            return FakeResponse({"status": "online"})

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        stx_client.check_status()
        assert captured["url"].endswith("/health")
        assert "/do" not in captured["url"]

    def test_custom_base_url(self, monkeypatch):
        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            return FakeResponse({"status": "online"})

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        stx_client.check_status(base_url="http://127.0.0.1:9999")
        assert captured["url"] == "http://127.0.0.1:9999/health"


class TestDescribeStatus:
    def test_formats_status_as_text(self, monkeypatch):
        monkeypatch.setattr(
            "stx_client.check_status",
            lambda base_url="": {"status": "online", "vault_files": 40, "model": "mistral"},
        )
        result = stx_client.describe_status()
        assert result == "STX_SYSTEM: online (modele: mistral, fichiers vault: 40)"

    def test_unreachable_returns_error_string(self, monkeypatch):
        def raise_error(base_url=""):
            raise TimeoutError("timed out")

        monkeypatch.setattr("stx_client.check_status", raise_error)
        result = stx_client.describe_status()
        assert result.startswith("stx: ")
        assert "timed out" in result
