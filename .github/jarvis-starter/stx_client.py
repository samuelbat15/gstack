from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

DEFAULT_BASE_URL = "http://127.0.0.1:8003"

# Status-only by design: this client never triggers STX_SYSTEM's own agent/LLM
# chain (no POST /do). STX_SYSTEM runs its own Ollama containers (stx_brain,
# starboxe_brain) alongside Jarvis's local model - a short, LLM-free /health
# check is safe to run anytime, but delegating tasks would risk two heavy
# CPU-only Ollama workloads competing at once on this machine. Keep it this
# way unless the user explicitly asks for task delegation.
TIMEOUT_SECONDS = 5


def check_status(base_url: str = "") -> dict:
    """Leve une exception si STX_SYSTEM est injoignable ou repond une erreur."""
    url = f"{(base_url or os.environ.get('STX_BASE_URL', '') or DEFAULT_BASE_URL).rstrip('/')}/health"
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def describe_status(base_url: str = "") -> str:
    """Ne leve jamais d'exception : erreur reseau/timeout -> chaine "stx: ..." retournee."""
    try:
        data = check_status(base_url)
    except Exception as exc:
        return f"stx: {exc}"

    status = data.get("status", "inconnu")
    vault_files = data.get("vault_files", "?")
    model = data.get("model", "?")
    return f"STX_SYSTEM: {status} (modele: {model}, fichiers vault: {vault_files})"
