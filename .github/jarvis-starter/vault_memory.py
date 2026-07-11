from __future__ import annotations

import subprocess
import time
from pathlib import Path

DEFAULT_VAULT_PATH = r"C:\Users\aiell\Documents\STARBOXE-Notes"
GRAPHIFY_TIMEOUT_SECONDS = 30
RECALL_MAX_CHARS = 4000
JARVIS_SUBFOLDER = "04_Agents_IA/Jarvis"


class VaultMemory:
    def __init__(self, vault_path: Path) -> None:
        self.vault_path = vault_path

    def remember(self, text: str) -> str:
        text = text.strip()
        if not text:
            return "vault_memory: texte vide, rien a enregistrer."

        if not self.vault_path.exists():
            return f"vault_memory: vault introuvable a {self.vault_path}"

        jarvis_dir = self.vault_path / JARVIS_SUBFOLDER
        jarvis_dir.mkdir(parents=True, exist_ok=True)

        timestamp = time.strftime("%Y-%m-%d_%H%M%S")
        note_path = jarvis_dir / f"{timestamp}.md"
        note_path.write_text(
            f"# Jarvis note\n\n{time.strftime('%Y-%m-%d %H:%M:%S')}\n\n{text}\n",
            encoding="utf-8",
        )

        error = self._run_graphify(["update", str(self.vault_path)])
        if error is not None:
            return error

        return "vault_memory: note enregistree dans le vault."

    def _run_graphify(self, args: list[str]) -> str | None:
        try:
            result = subprocess.run(
                ["graphify", *args],
                capture_output=True,
                text=True,
                timeout=GRAPHIFY_TIMEOUT_SECONDS,
            )
        except FileNotFoundError:
            return "vault_memory: graphify introuvable dans le PATH."
        except subprocess.TimeoutExpired:
            return "vault_memory: graphify a depasse le delai (30s)."

        if result.returncode != 0:
            return f"vault_memory: erreur graphify - {result.stderr.strip()[:300]}"

        return None
