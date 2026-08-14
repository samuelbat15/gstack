from __future__ import annotations

import json
import os
import secrets
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from jarvis import Config, Jarvis, load_config, load_env_file
from vault_memory import DEFAULT_VAULT_PATH

DAEMON_INTERVAL_SECONDS = 30
DASHBOARD_PATH = Path(__file__).resolve().parent / "dashboard.html"
SESSION_COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 jours - usage personnel, pas de rotation


def is_loopback(address: str) -> bool:
    return address in {"127.0.0.1", "::1"}


def extract_bearer_token(headers: Any) -> str:
    value = headers.get("Authorization", "")
    if value.startswith("Bearer "):
        return value[len("Bearer ") :].strip()
    return ""


def extract_session_cookie(headers: Any) -> str:
    cookie_header = headers.get("Cookie", "") or ""
    for part in cookie_header.split(";"):
        if "=" not in part:
            continue
        key, value = part.strip().split("=", 1)
        if key == "jarvis_session":
            return value
    return ""


class SessionStore:
    """In-memory session ids handed out once a client proves it knows the API token.

    Keeps the raw token out of cookies/browser history after the first login.
    """

    def __init__(self) -> None:
        self._sessions: set[str] = set()

    def create(self) -> str:
        session_id = secrets.token_urlsafe(32)
        self._sessions.add(session_id)
        return session_id

    def is_valid(self, session_id: str) -> bool:
        return bool(session_id) and session_id in self._sessions


def is_authorized(client_ip: str, api_token: str, sessions: SessionStore, bearer: str, cookie: str) -> bool:
    if is_loopback(client_ip):
        return True
    if api_token and bearer == api_token:
        return True
    return sessions.is_valid(cookie)


class RateLimiter:
    """Sliding-window request counter, per client IP.

    Loopback is exempt at the call site (not here) - the dashboard alone polls
    /status and /reminders every 1.5s, which would blow past any reasonable
    remote-facing limit. Checked before auth, so it also throttles brute-force
    token/login attempts, not just authenticated traffic.
    """

    def __init__(self, max_requests: int = 60, window_seconds: float = 60.0) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def is_allowed(self, client_ip: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        cutoff = now - self.window_seconds
        with self._lock:
            hits = self._hits.setdefault(client_ip, [])
            while hits and hits[0] < cutoff:
                hits.pop(0)
            if len(hits) >= self.max_requests:
                return False
            hits.append(now)
            return True


class ConfirmGate:
    """Two-phase confirmation for actions that would otherwise be silently denied.

    A client that gets ``needs_confirmation: true`` back resends the exact same
    ``text`` with ``confirm: true``; ``handle()`` re-derives the same target and
    this gate approves that single confirm() call so the action actually runs.
    """

    def __init__(self) -> None:
        self.approve_next = False
        self.pending_action: str | None = None

    def reset(self) -> None:
        self.pending_action = None

    def __call__(self, action: str) -> bool:
        if self.approve_next:
            self.approve_next = False
            return True
        self.pending_action = action
        return False


class ReminderDaemonThread(threading.Thread):
    def __init__(self, jarvis: Jarvis, interval: float = DAEMON_INTERVAL_SECONDS) -> None:
        super().__init__(daemon=True)
        self.jarvis = jarvis
        self.interval = interval
        self._stop_event = threading.Event()

    def run(self) -> None:
        while not self._stop_event.is_set():
            now = datetime.now()
            for reminder in self.jarvis.reminders.due(now):
                self.jarvis.notifier.notify("Jarvis", reminder["text"])
                self.jarvis.reminders.mark_fired(reminder["id"])
            self._stop_event.wait(self.interval)

    def stop(self) -> None:
        self._stop_event.set()


def build_app(config_path: Path, data_dir: Path, vault_path: Path) -> tuple[Jarvis, ConfirmGate]:
    config = load_config(config_path)
    gate = ConfirmGate()
    responses: list[str] = []
    jarvis = Jarvis(
        config=config,
        voice=False,
        data_dir=data_dir,
        vault_path=vault_path,
        output_sink=responses.append,
        confirm_fn=gate,
    )
    jarvis._http_responses = responses  # type: ignore[attr-defined]
    return jarvis, gate


def make_handler(
    jarvis: Jarvis,
    gate: ConfirmGate,
    api_token: str = "",
    sessions: SessionStore | None = None,
    rate_limiter: RateLimiter | None = None,
) -> type[BaseHTTPRequestHandler]:
    responses: list[str] = jarvis._http_responses  # type: ignore[attr-defined]
    sessions = sessions if sessions is not None else SessionStore()
    rate_limiter = rate_limiter if rate_limiter is not None else RateLimiter()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
            pass

        def _authorized(self) -> bool:
            return is_authorized(
                self.client_address[0],
                api_token,
                sessions,
                extract_bearer_token(self.headers),
                extract_session_cookie(self.headers),
            )

        def _rate_limited(self) -> bool:
            client_ip = self.client_address[0]
            if is_loopback(client_ip):
                return False
            return not rate_limiter.is_allowed(client_ip)

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json_body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", 0) or 0)
            if length == 0:
                return {}
            raw = self.rfile.read(length)
            try:
                data = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                return {}
            return data if isinstance(data, dict) else {}

        def do_GET(self) -> None:  # noqa: N802 - stdlib method name
            if self._rate_limited():
                self._send_json(429, {"error": "trop de requetes, reessaie plus tard"})
                return

            parsed = urlsplit(self.path)

            if parsed.path == "/":
                token_param = parse_qs(parsed.query).get("token", [""])[0]
                if token_param and api_token and secrets.compare_digest(token_param, api_token):
                    session_id = sessions.create()
                    self.send_response(302)
                    self.send_header("Location", "/")
                    self.send_header(
                        "Set-Cookie",
                        f"jarvis_session={session_id}; HttpOnly; SameSite=Strict; Max-Age={SESSION_COOKIE_MAX_AGE}",
                    )
                    self.end_headers()
                    return
                if not self._authorized():
                    self._send_json(401, {"error": "authentification requise"})
                    return
                body = DASHBOARD_PATH.read_text(encoding="utf-8").encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if not self._authorized():
                self._send_json(401, {"error": "authentification requise"})
                return

            if parsed.path == "/status":
                self._send_json(200, {"status": jarvis.status()})
                return
            if parsed.path == "/reminders":
                self._send_json(200, {"reminders": jarvis.reminders.pending()})
                return
            self._send_json(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802 - stdlib method name
            if self._rate_limited():
                self._send_json(429, {"error": "trop de requetes, reessaie plus tard"})
                return

            if not self._authorized():
                self._send_json(401, {"error": "authentification requise"})
                return

            if self.path == "/message":
                body = self._read_json_body()
                text = str(body.get("text", "")).strip()
                if not text:
                    self._send_json(400, {"error": "text manquant"})
                    return
                if bool(body.get("confirm")):
                    gate.approve_next = True
                gate.reset()
                responses.clear()
                jarvis.handle(text)
                self._send_json(
                    200,
                    {
                        "response": "\n".join(responses),
                        "needs_confirmation": gate.pending_action is not None,
                        "action": gate.pending_action,
                    },
                )
                return

            if self.path == "/reminders":
                body = self._read_json_body()
                text = str(body.get("text", "")).strip()
                when = str(body.get("when", "")).strip()
                if not text or not when:
                    self._send_json(400, {"error": "when/text manquant"})
                    return
                message = jarvis.create_reminder_from_text(f"{when} de {text}")
                self._send_json(201, {"message": message})
                return

            self._send_json(404, {"error": "not found"})

    return Handler


def run_server(host: str | None = None, port: int | None = None) -> None:
    base_dir = Path(__file__).resolve().parent
    load_env_file(base_dir / ".env")

    host = host or os.environ.get("JARVIS_HOST", "127.0.0.1").strip()
    port = port or int(os.environ.get("JARVIS_PORT", "8787"))
    api_token = os.environ.get("JARVIS_API_TOKEN", "").strip()

    if not is_loopback(host) and not api_token:
        raise SystemExit(
            f"JARVIS_HOST={host} n'est pas local mais JARVIS_API_TOKEN est vide. "
            "Genere un token (python -c \"import secrets; print(secrets.token_urlsafe(32))\") "
            "et ajoute JARVIS_API_TOKEN=<token> dans .env avant d'exposer Jarvis au reseau."
        )

    config_path = base_dir / "config.json"
    data_dir = Path(os.environ.get("JARVIS_DATA_DIR", base_dir / "data"))
    if not data_dir.is_absolute():
        data_dir = base_dir / data_dir
    vault_path = Path(os.environ.get("JARVIS_VAULT_PATH", "").strip() or DEFAULT_VAULT_PATH)

    jarvis, gate = build_app(config_path, data_dir, vault_path)
    daemon = ReminderDaemonThread(jarvis)
    daemon.start()

    rate_limit_max = int(os.environ.get("JARVIS_RATE_LIMIT", "60"))
    rate_limit_window = float(os.environ.get("JARVIS_RATE_LIMIT_WINDOW", "60"))
    handler = make_handler(
        jarvis,
        gate,
        api_token=api_token,
        sessions=SessionStore(),
        rate_limiter=RateLimiter(max_requests=rate_limit_max, window_seconds=rate_limit_window),
    )
    httpd = ThreadingHTTPServer((host, port), handler)
    if api_token:
        print(f"Jarvis backend en ecoute sur http://{host}:{port} (token requis hors localhost)")
        print(f"Depuis un autre appareil, ouvre: http://{host}:{port}/?token={api_token}")
    else:
        print(f"Jarvis backend en ecoute sur http://{host}:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        daemon.stop()
        httpd.shutdown()


if __name__ == "__main__":
    run_server()
