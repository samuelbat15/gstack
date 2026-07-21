from __future__ import annotations

import http.client
import json
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta

import pytest

from jarvis import Config
from server import (
    ConfirmGate,
    ReminderDaemonThread,
    SessionStore,
    build_app,
    extract_bearer_token,
    extract_session_cookie,
    is_authorized,
    is_loopback,
    make_handler,
)
from http.server import ThreadingHTTPServer


def make_config(**overrides) -> Config:
    defaults = dict(
        assistant_name="Jarvis",
        confirm_actions=True,
        sites={"youtube": "https://www.youtube.com"},
        apps={"calculatrice": "calc.exe"},
    )
    defaults.update(overrides)
    return Config(**defaults)


@pytest.fixture
def running_server(tmp_path, monkeypatch):
    monkeypatch.setattr("server.load_config", lambda path: make_config())
    jarvis, gate = build_app(tmp_path / "config.json", tmp_path, tmp_path / "vault")
    handler = make_handler(jarvis, gate)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host, port = httpd.server_address
    base_url = f"http://{host}:{port}"
    try:
        yield base_url, jarvis, gate
    finally:
        httpd.shutdown()
        thread.join(timeout=2)


def request_json(url: str, method: str = "GET", payload: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


class FakeHeaders(dict):
    def get(self, key, default=""):  # http.client.HTTPMessage-style default
        return super().get(key, default)


class TestIsLoopback:
    def test_ipv4_and_ipv6_loopback_are_loopback(self):
        assert is_loopback("127.0.0.1") is True
        assert is_loopback("::1") is True

    def test_lan_address_is_not_loopback(self):
        assert is_loopback("192.168.1.42") is False


class TestExtractCredentials:
    def test_extract_bearer_token_from_authorization_header(self):
        assert extract_bearer_token(FakeHeaders({"Authorization": "Bearer abc123"})) == "abc123"

    def test_extract_bearer_token_missing_returns_empty(self):
        assert extract_bearer_token(FakeHeaders({})) == ""

    def test_extract_session_cookie_from_cookie_header(self):
        headers = FakeHeaders({"Cookie": "other=1; jarvis_session=xyz; another=2"})
        assert extract_session_cookie(headers) == "xyz"

    def test_extract_session_cookie_missing_returns_empty(self):
        assert extract_session_cookie(FakeHeaders({})) == ""


class TestSessionStore:
    def test_created_session_is_valid(self):
        sessions = SessionStore()
        session_id = sessions.create()
        assert sessions.is_valid(session_id) is True

    def test_unknown_session_is_invalid(self):
        assert SessionStore().is_valid("not-a-real-session") is False


class TestIsAuthorized:
    def test_loopback_client_is_always_authorized(self):
        assert is_authorized("127.0.0.1", "", SessionStore(), "", "") is True

    def test_lan_client_without_credentials_is_rejected(self):
        assert is_authorized("192.168.1.42", "secret", SessionStore(), "", "") is False

    def test_lan_client_with_matching_bearer_token_is_authorized(self):
        assert is_authorized("192.168.1.42", "secret", SessionStore(), "secret", "") is True

    def test_lan_client_with_valid_session_cookie_is_authorized(self):
        sessions = SessionStore()
        session_id = sessions.create()
        assert is_authorized("192.168.1.42", "secret", sessions, "", session_id) is True

    def test_lan_client_with_wrong_bearer_token_is_rejected(self):
        assert is_authorized("192.168.1.42", "secret", SessionStore(), "wrong", "") is False


class TestTokenLoginRoute:
    def test_valid_token_query_param_sets_session_cookie(self, tmp_path, monkeypatch):
        monkeypatch.setattr("server.load_config", lambda path: make_config())
        jarvis, gate = build_app(tmp_path / "config.json", tmp_path, tmp_path / "vault")
        handler = make_handler(jarvis, gate, api_token="secret-token")
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            host, port = httpd.server_address
            conn = http.client.HTTPConnection(host, port, timeout=5)
            conn.request("GET", "/?token=secret-token")
            response = conn.getresponse()
            cookie = response.getheader("Set-Cookie", "")
            response.read()
            conn.close()
            assert response.status == 302
            assert "jarvis_session=" in cookie
            assert "HttpOnly" in cookie
        finally:
            httpd.shutdown()
            thread.join(timeout=2)


class TestDashboardRoute:
    def test_root_serves_dashboard_html(self, running_server):
        base_url, _, _ = running_server
        req = urllib.request.Request(f"{base_url}/")
        with urllib.request.urlopen(req, timeout=5) as response:
            assert response.status == 200
            assert response.headers["Content-Type"].startswith("text/html")
            body = response.read().decode("utf-8")
        assert "<title>Jarvis" in body


class TestStatusEndpoint:
    def test_status_returns_jarvis_status_string(self, running_server):
        base_url, jarvis, _ = running_server
        status, payload = request_json(f"{base_url}/status")
        assert status == 200
        assert payload["status"] == jarvis.status()


class TestMessageEndpoint:
    def test_message_returns_captured_response_text(self, running_server):
        base_url, _, _ = running_server
        status, payload = request_json(f"{base_url}/message", "POST", {"text": "heure"})
        assert status == 200
        assert "Il est" in payload["response"]
        assert payload["needs_confirmation"] is False

    def test_missing_text_is_a_400(self, running_server):
        base_url, _, _ = running_server
        status, payload = request_json(f"{base_url}/message", "POST", {"text": "  "})
        assert status == 400
        assert "error" in payload

    def test_confirmable_action_is_denied_and_reported(self, running_server):
        base_url, _, _ = running_server
        status, payload = request_json(f"{base_url}/message", "POST", {"text": "ouvre youtube"})
        assert status == 200
        assert payload["needs_confirmation"] is True
        assert "youtube" in payload["action"]

    def test_resending_with_confirm_true_approves_the_same_action(self, running_server):
        base_url, _, _ = running_server
        request_json(f"{base_url}/message", "POST", {"text": "ouvre youtube"})
        status, payload = request_json(
            f"{base_url}/message", "POST", {"text": "ouvre youtube", "confirm": True}
        )
        assert status == 200
        assert payload["needs_confirmation"] is False


class TestRemindersEndpoint:
    def test_get_reminders_starts_empty(self, running_server):
        base_url, _, _ = running_server
        status, payload = request_json(f"{base_url}/reminders")
        assert status == 200
        assert payload["reminders"] == []

    def test_post_reminder_then_get_lists_it(self, running_server):
        base_url, _, _ = running_server
        status, payload = request_json(
            f"{base_url}/reminders", "POST", {"when": "dans 20 minutes", "text": "appeler Sam"}
        )
        assert status == 201
        assert "programme" in payload["message"]

        status, payload = request_json(f"{base_url}/reminders")
        assert status == 200
        assert len(payload["reminders"]) == 1
        assert payload["reminders"][0]["text"] == "appeler Sam"

    def test_missing_fields_is_a_400(self, running_server):
        base_url, _, _ = running_server
        status, payload = request_json(f"{base_url}/reminders", "POST", {"when": "dans 20 minutes"})
        assert status == 400


class TestConfirmGate:
    def test_denies_by_default_and_records_action(self):
        gate = ConfirmGate()
        assert gate("ouvrir youtube") is False
        assert gate.pending_action == "ouvrir youtube"

    def test_approve_next_is_single_use(self):
        gate = ConfirmGate()
        gate.approve_next = True
        assert gate("ouvrir youtube") is True
        assert gate("ouvrir youtube") is False


class TestReminderDaemonThread:
    def test_fires_due_reminder_and_marks_it(self, tmp_path, monkeypatch):
        monkeypatch.setattr("server.load_config", lambda path: make_config())
        jarvis, _ = build_app(tmp_path / "config.json", tmp_path, tmp_path / "vault")
        jarvis.reminders.add("appeler Sam", datetime.now() - timedelta(seconds=1))

        notified = []
        monkeypatch.setattr(jarvis.notifier, "notify", lambda title, message: notified.append(message))

        daemon = ReminderDaemonThread(jarvis, interval=0.05)
        daemon.start()
        try:
            for _ in range(40):
                if notified:
                    break
                threading.Event().wait(0.05)
        finally:
            daemon.stop()
            daemon.join(timeout=2)

        assert notified == ["appeler Sam"]
        assert jarvis.reminders.pending() == []
