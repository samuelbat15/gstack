from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

DEFAULT_VAULT_PATH = r"C:\Users\aiell\Documents\STARBOXE-Notes"
GRAPHIFY_TIMEOUT_SECONDS = 30
RECALL_MAX_CHARS = 4000
JARVIS_SUBFOLDER = "04_Agents_IA/Jarvis"


def _graphify_executable() -> str:
    # shutil.which resolves PATHEXT (.cmd/.ps1) on Windows, unlike a bare
    # subprocess.run(["graphify", ...]) which only matches an exact filename.
    return shutil.which("graphify") or "graphify"


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

        self._launch_graphify_update_in_background()

        return "vault_memory: note enregistree dans le vault."

    def _launch_graphify_update_in_background(self) -> None:
        # graphify update peut prendre plusieurs minutes sur un gros vault, et
        # subprocess timeout ne tue pas fiablement le node.exe lance par le
        # wrapper .cmd sur Windows (le processus reste orphelin). On lance
        # donc en detache sans jamais attendre ni lire sa sortie.
        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP

        try:
            subprocess.Popen(
                [_graphify_executable(), "update", str(self.vault_path)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
                start_new_session=(os.name != "nt"),
            )
        except FileNotFoundError:
            pass

    def recall(self, query: str) -> str:
        query = query.strip()
        if not query:
            return "vault_memory: requete vide."

        graph_path = self.vault_path / ".graphify" / "graph.json"
        if not graph_path.exists():
            return (
                f"vault_memory: graphe absent, lance 'graphify {self.vault_path}' "
                "pour l'indexer."
            )

        try:
            result = subprocess.run(
                [_graphify_executable(), "query", query, "--graph", str(graph_path)],
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

        output = result.stdout.strip()
        if len(output) > RECALL_MAX_CHARS:
            output = output[:RECALL_MAX_CHARS] + " [tronque]"
        return output or "vault_memory: aucun resultat."
