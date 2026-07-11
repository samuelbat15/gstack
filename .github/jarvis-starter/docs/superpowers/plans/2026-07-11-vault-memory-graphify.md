# Mémoire vault Obsidian via graphify — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remplacer le mini-index memoire maison de Jarvis par une vraie
integration au vault Obsidian de l'utilisateur via la CLI `graphify`, et
finir de brancher le systeme de revisions/A-B testing (`GraphityRuntime`)
qui existe deja dans le code mais n'est jamais instancie.

**Architecture:** Nouveau module `vault_memory.py` (ecriture de notes
markdown dans le vault + appels subprocess a `graphify update`/`graphify
query`). `graphity_runtime.py` perd son `GraphityMemory` maison et utilise
`VaultMemory` a la place. `jarvis.py` instancie enfin `GraphityRuntime`,
route `run_agentic` via `GraphityRuntime.invoke()`, et cable les commandes
directes `graphity *` ainsi que les outils agentic `graphity_recall`/
`graphity_remember`.

**Tech Stack:** Python 3.11 (stdlib + `subprocess`), pytest pour les tests
(nouveau, aucune suite existante avant ce plan), CLI externe `graphify`
(deja installee globalement, verifiee fonctionnelle sur le vault cible).

---

## Fichiers concernes

- Create: `jarvis-starter/vault_memory.py` — `VaultMemory` (remember/recall
  contre le vrai `graphify`), constante `DEFAULT_VAULT_PATH` partagee.
- Modify: `jarvis-starter/graphity_runtime.py` — retire `GraphityMemory` et
  `normalize_key` (dead code apres migration), branche `VaultMemory`,
  simplifie `invoke()` (plus d'auto-remember a chaque tour).
- Modify: `jarvis-starter/graphity_cli.py` — seul autre consommateur de
  `GraphityRuntime`/`GraphityMemory`, casse sinon (decouvert pendant la
  planification, absent des deux specs).
- Modify: `jarvis-starter/jarvis.py` — instancie `GraphityRuntime`, route
  `run_agentic`, cable `handle()` et `execute_agent_tool()`.
- Modify: `jarvis-starter/env.template` — ajoute `JARVIS_VAULT_PATH`.
- Modify: `jarvis-starter/README.md` — documente la memoire vault et les
  revisions.
- Create: `jarvis-starter/requirements-dev.txt` — `pytest>=8.0`.
- Create: `jarvis-starter/pytest.ini` — rend `vault_memory`/`graphity_runtime`
  importables depuis `tests/` sans manipulation manuelle de `sys.path`.
- Create: `jarvis-starter/tests/test_vault_memory.py`
- Create: `jarvis-starter/tests/test_graphity_runtime.py`

---

### Task 1: Scaffolding de tests + `VaultMemory.remember` (chemin heureux)

**Files:**
- Create: `jarvis-starter/requirements-dev.txt`
- Create: `jarvis-starter/pytest.ini`
- Create: `jarvis-starter/vault_memory.py`
- Test: `jarvis-starter/tests/test_vault_memory.py`

- [ ] **Step 1: Vérifier/créer le fichier de dépendances de dev**

`jarvis-starter/requirements-dev.txt` (peut déjà exister — une spec
séparée sur cette branche, `2026-07-11-agentic-loop-robustness-design.md`,
l'a créé en premier pour ses propres tests ; si le fichier existe déjà
avec ce contenu exact, ne rien faire) :

```text
pytest>=8.0
```

- [ ] **Step 2: Vérifier/créer la config pytest**

`jarvis-starter/pytest.ini` (même remarque — probablement déjà présent) :

```ini
[pytest]
pythonpath = .
```

- [ ] **Step 3: Installer les dépendances de dev**

Run (depuis `jarvis-starter/`):

```powershell
pip install -r requirements-dev.txt
```

Expected: installation de `pytest` sans erreur.

- [ ] **Step 4: Écrire les tests qui échouent pour `remember` (cas de base)**

`jarvis-starter/tests/test_vault_memory.py`:

```python
from __future__ import annotations

import subprocess

from vault_memory import VaultMemory


def make_completed_process(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class TestRemember:
    def test_vault_not_found(self, tmp_path):
        memory = VaultMemory(tmp_path / "missing-vault")
        result = memory.remember("un fait")
        assert "vault introuvable" in result

    def test_empty_text(self, tmp_path):
        memory = VaultMemory(tmp_path)
        result = memory.remember("   ")
        assert "texte vide" in result

    def test_success_writes_note_and_rebuilds(self, tmp_path, monkeypatch):
        memory = VaultMemory(tmp_path)
        calls = []

        def fake_run(args, **kwargs):
            calls.append(args)
            return make_completed_process(returncode=0, stdout="ok")

        monkeypatch.setattr("vault_memory.subprocess.run", fake_run)
        result = memory.remember("il faut relancer la campagne SEO")

        assert "enregistree" in result
        notes = list((tmp_path / "04_Agents_IA" / "Jarvis").glob("*.md"))
        assert len(notes) == 1
        assert "relancer la campagne SEO" in notes[0].read_text(encoding="utf-8")
        assert calls == [["graphify", "update", str(tmp_path)]]
```

- [ ] **Step 5: Vérifier que les tests échouent (module manquant)**

Run:

```powershell
python -m pytest tests/test_vault_memory.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'vault_memory'`.

- [ ] **Step 6: Implémenter `VaultMemory.remember` (chemin heureux)**

`jarvis-starter/vault_memory.py`:

```python
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
```

- [ ] **Step 7: Vérifier que les tests passent**

Run:

```powershell
python -m pytest tests/test_vault_memory.py -v
```

Expected: 3 passed.

- [ ] **Step 8: Commit**

```powershell
git add jarvis-starter/requirements-dev.txt jarvis-starter/pytest.ini jarvis-starter/vault_memory.py jarvis-starter/tests/test_vault_memory.py
git commit -m "feat: scaffold pytest + VaultMemory.remember happy path"
```

---

### Task 2: `VaultMemory.remember` — gestion d'erreurs

**Files:**
- Modify: `jarvis-starter/tests/test_vault_memory.py`
- Modify: `jarvis-starter/vault_memory.py` (déjà correct depuis Task 1 — cette
  tâche ajoute seulement les tests qui confirment le comportement des
  branches d'erreur déjà écrites)

- [ ] **Step 1: Ajouter les tests d'erreur**

Ajouter à `jarvis-starter/tests/test_vault_memory.py`, dans `TestRemember` :

```python
    def test_graphify_not_found(self, tmp_path, monkeypatch):
        memory = VaultMemory(tmp_path)

        def fake_run(args, **kwargs):
            raise FileNotFoundError()

        monkeypatch.setattr("vault_memory.subprocess.run", fake_run)
        result = memory.remember("un fait")
        assert "introuvable dans le PATH" in result

    def test_graphify_timeout(self, tmp_path, monkeypatch):
        memory = VaultMemory(tmp_path)

        def fake_run(args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="graphify", timeout=30)

        monkeypatch.setattr("vault_memory.subprocess.run", fake_run)
        result = memory.remember("un fait")
        assert "delai" in result

    def test_graphify_nonzero_exit(self, tmp_path, monkeypatch):
        memory = VaultMemory(tmp_path)

        def fake_run(args, **kwargs):
            return make_completed_process(returncode=1, stderr="boom")

        monkeypatch.setattr("vault_memory.subprocess.run", fake_run)
        result = memory.remember("un fait")
        assert "erreur graphify" in result
        assert "boom" in result
```

- [ ] **Step 2: Lancer les tests**

Run:

```powershell
python -m pytest tests/test_vault_memory.py -v
```

Expected: 6 passed (aucun changement de code necessaire, `remember` gere
deja ces cas via `_run_graphify` ecrit en Task 1 — ce step confirme la
couverture).

- [ ] **Step 3: Commit**

```powershell
git add jarvis-starter/tests/test_vault_memory.py
git commit -m "test: cover VaultMemory.remember error paths"
```

---

### Task 3: `VaultMemory.recall`

**Files:**
- Modify: `jarvis-starter/tests/test_vault_memory.py`
- Modify: `jarvis-starter/vault_memory.py`

- [ ] **Step 1: Écrire les tests qui échouent pour `recall`**

Ajouter à `jarvis-starter/tests/test_vault_memory.py` :

```python
class TestRecall:
    def test_graph_missing(self, tmp_path):
        memory = VaultMemory(tmp_path)
        result = memory.recall("campagne SEO")
        assert "graphe absent" in result

    def test_empty_query(self, tmp_path):
        memory = VaultMemory(tmp_path)
        result = memory.recall("   ")
        assert "requete vide" in result

    def test_success_returns_stdout(self, tmp_path, monkeypatch):
        graph_dir = tmp_path / ".graphify"
        graph_dir.mkdir()
        (graph_dir / "graph.json").write_text("{}", encoding="utf-8")
        memory = VaultMemory(tmp_path)

        def fake_run(args, **kwargs):
            return make_completed_process(returncode=0, stdout="entity:seo -> campagne 2026")

        monkeypatch.setattr("vault_memory.subprocess.run", fake_run)
        result = memory.recall("campagne SEO")
        assert result == "entity:seo -> campagne 2026"

    def test_truncates_long_output(self, tmp_path, monkeypatch):
        graph_dir = tmp_path / ".graphify"
        graph_dir.mkdir()
        (graph_dir / "graph.json").write_text("{}", encoding="utf-8")
        memory = VaultMemory(tmp_path)

        def fake_run(args, **kwargs):
            return make_completed_process(returncode=0, stdout="x" * 5000)

        monkeypatch.setattr("vault_memory.subprocess.run", fake_run)
        result = memory.recall("campagne SEO")
        assert result.endswith("[tronque]")
        assert len(result) <= 4000 + len(" [tronque]")

    def test_graphify_not_found(self, tmp_path, monkeypatch):
        graph_dir = tmp_path / ".graphify"
        graph_dir.mkdir()
        (graph_dir / "graph.json").write_text("{}", encoding="utf-8")
        memory = VaultMemory(tmp_path)

        def fake_run(args, **kwargs):
            raise FileNotFoundError()

        monkeypatch.setattr("vault_memory.subprocess.run", fake_run)
        result = memory.recall("campagne SEO")
        assert "introuvable dans le PATH" in result
```

- [ ] **Step 2: Vérifier que les nouveaux tests échouent**

Run:

```powershell
python -m pytest tests/test_vault_memory.py -v
```

Expected: FAIL — `AttributeError: 'VaultMemory' object has no attribute 'recall'`.

- [ ] **Step 3: Implémenter `recall`**

Ajouter à `jarvis-starter/vault_memory.py`, dans la classe `VaultMemory` :

```python
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
                ["graphify", "query", query, "--graph", str(graph_path)],
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
```

- [ ] **Step 4: Vérifier que tous les tests passent**

Run:

```powershell
python -m pytest tests/test_vault_memory.py -v
```

Expected: 11 passed.

- [ ] **Step 5: Commit**

```powershell
git add jarvis-starter/vault_memory.py jarvis-starter/tests/test_vault_memory.py
git commit -m "feat: implement VaultMemory.recall against the real graphify graph"
```

---

### Task 4: Réécrire `graphity_runtime.py` pour utiliser `VaultMemory`

**Files:**
- Modify: `jarvis-starter/graphity_runtime.py` (remplacement complet du fichier)
- Test: `jarvis-starter/tests/test_graphity_runtime.py`

- [ ] **Step 1: Écrire les tests qui échouent pour `GraphityRuntime`**

`jarvis-starter/tests/test_graphity_runtime.py` :

```python
from __future__ import annotations

import pytest

from graphity_runtime import GraphityRuntime, GraphityStateError


def make_runtime(tmp_path):
    return GraphityRuntime(tmp_path / "data", tmp_path / "vault")


class TestBootstrap:
    def test_bootstrap_creates_two_default_revisions(self, tmp_path):
        runtime = make_runtime(tmp_path)
        revisions = runtime.list_revisions()
        assert [r["label"] for r in revisions] == ["v1-fast-local", "v2-graph-memory"]
        assert revisions[0]["agent_kind"] == "fast"
        assert revisions[1]["agent_kind"] == "graph"

    def test_bootstrap_is_idempotent(self, tmp_path):
        runtime = make_runtime(tmp_path)
        runtime.ensure_bootstrap()
        runtime.ensure_bootstrap()
        assert len(runtime.list_revisions()) == 2


class TestSplit:
    def test_manual_split_valid(self, tmp_path):
        runtime = make_runtime(tmp_path)
        runtime.set_manual_split({"1": 50, "2": 50})
        assert runtime.describe_traffic() == (
            "manual split:\n- 50% -> v1-fast-local\n- 50% -> v2-graph-memory"
        )

    def test_manual_split_invalid_total(self, tmp_path):
        runtime = make_runtime(tmp_path)
        with pytest.raises(GraphityStateError):
            runtime.set_manual_split({"1": 50, "2": 10})

    def test_manual_split_unknown_revision(self, tmp_path):
        runtime = make_runtime(tmp_path)
        with pytest.raises(GraphityStateError):
            runtime.set_manual_split({"99": 100})


class TestRouting:
    def test_always_latest_returns_latest(self, tmp_path):
        runtime = make_runtime(tmp_path)
        revision = runtime.route_revision()
        assert revision["label"] == "v2-graph-memory"

    def test_manual_split_routes_deterministically(self, tmp_path, monkeypatch):
        runtime = make_runtime(tmp_path)
        runtime.set_manual_split({"1": 50, "2": 50})

        monkeypatch.setattr("graphity_runtime.random.randint", lambda a, b: 10)
        assert runtime.route_revision()["label"] == "v1-fast-local"

        monkeypatch.setattr("graphity_runtime.random.randint", lambda a, b: 90)
        assert runtime.route_revision()["label"] == "v2-graph-memory"

    def test_resolve_revision_by_number_label_or_name(self, tmp_path):
        runtime = make_runtime(tmp_path)
        by_number = runtime.resolve_revision("1")
        by_label = runtime.resolve_revision("v1-fast-local")
        assert by_number == by_label
        assert by_number is not None


class TestInvoke:
    def test_invoke_uses_recall_and_does_not_write(self, tmp_path, monkeypatch):
        runtime = make_runtime(tmp_path)
        recall_calls = []
        remember_calls = []
        monkeypatch.setattr(runtime.memory, "recall", lambda q: recall_calls.append(q) or "contexte")
        monkeypatch.setattr(runtime.memory, "remember", lambda t: remember_calls.append(t))

        result = runtime.invoke("bonjour", executor=lambda revision, context: f"{revision['label']}:{context}")

        assert result.response == "v2-graph-memory:contexte"
        assert recall_calls == ["bonjour"]
        assert remember_calls == []
```

- [ ] **Step 2: Vérifier que les tests échouent**

Run:

```powershell
python -m pytest tests/test_graphity_runtime.py -v
```

Expected: FAIL — `TypeError: GraphityRuntime.__init__() missing 1 required
positional argument: 'vault_path'`.

- [ ] **Step 3: Réécrire `graphity_runtime.py`**

Remplacer tout le contenu de `jarvis-starter/graphity_runtime.py` par :

```python
from __future__ import annotations

import hashlib
import json
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from vault_memory import VaultMemory


DEFAULT_ENGINE_NAME = "jarvis-local"


@dataclass(frozen=True)
class InvocationResult:
    revision_name: str
    revision_label: str
    response: str


class GraphityStateError(ValueError):
    pass


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def read_json(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def stable_hash(data: dict[str, Any]) -> str:
    encoded = json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


class GraphityRuntime:
    def __init__(self, data_dir: Path, vault_path: Path, engine_name: str = DEFAULT_ENGINE_NAME) -> None:
        self.data_dir = data_dir
        self.state_path = data_dir / "state.json"
        self.memory = VaultMemory(vault_path)
        self.engine_name = engine_name
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def ensure_bootstrap(self) -> None:
        state = self.load_state()
        if state.get("revisions"):
            return

        self.create_revision(
            label="v1-fast-local",
            agent_kind="fast",
            instructions=(
                "Version rapide: reponds court, utilise les outils seulement quand ils sont utiles, "
                "et privilegie une reponse immediate."
            ),
        )
        self.create_revision(
            label="v2-graph-memory",
            agent_kind="graph",
            instructions=(
                "Version Graphity: utilise la memoire graphe quand la demande depend du contexte, "
                "puis donne une reponse concise avec les observations utiles."
            ),
        )

    def load_state(self) -> dict[str, Any]:
        fallback = {
            "engine": {
                "name": self.engine_name,
                "resource_name": f"local/reasoningEngines/{self.engine_name}",
                "created_at": now_iso(),
            },
            "traffic": {"mode": "always_latest", "targets": []},
            "revisions": [],
        }
        return read_json(self.state_path, fallback)

    def save_state(self, state: dict[str, Any]) -> None:
        write_json(self.state_path, state)

    def create_revision(self, label: str, agent_kind: str, instructions: str) -> dict[str, Any]:
        state = self.load_state()
        revisions = state.setdefault("revisions", [])
        number = len(revisions) + 1
        engine_resource = state["engine"]["resource_name"]
        revision_name = f"{engine_resource}/runtimeRevisions/{number}"
        snapshot = {
            "label": label,
            "agent_kind": agent_kind,
            "instructions": instructions,
        }
        revision = {
            "name": revision_name,
            "number": number,
            "label": label,
            "agent_kind": agent_kind,
            "instructions": instructions,
            "created_at": now_iso(),
            "snapshot_hash": stable_hash(snapshot),
        }
        revisions.append(revision)
        state["traffic"] = {"mode": "always_latest", "targets": []}
        self.save_state(state)
        return revision

    def list_revisions(self) -> list[dict[str, Any]]:
        self.ensure_bootstrap()
        return list(self.load_state().get("revisions", []))

    def describe_traffic(self) -> str:
        self.ensure_bootstrap()
        state = self.load_state()
        traffic = state.get("traffic", {})
        if traffic.get("mode") != "manual":
            latest = self.latest_revision()
            return f"always_latest -> {latest['label']} ({latest['number']})"

        lines = ["manual split:"]
        for target in traffic.get("targets", []):
            revision = self.resolve_revision(str(target.get("runtime_revision_name", "")))
            label = revision["label"] if revision else str(target.get("runtime_revision_name", "unknown"))
            lines.append(f"- {target.get('percent', 0)}% -> {label}")
        return "\n".join(lines)

    def set_always_latest(self) -> None:
        state = self.load_state()
        state["traffic"] = {"mode": "always_latest", "targets": []}
        self.save_state(state)

    def set_manual_split(self, targets: dict[str, int]) -> None:
        self.ensure_bootstrap()
        if sum(targets.values()) != 100:
            raise GraphityStateError("Les pourcentages doivent faire 100.")

        normalized_targets = []
        for key, percent in targets.items():
            revision = self.resolve_revision(key)
            if revision is None:
                raise GraphityStateError(f"Revision introuvable: {key}")
            if percent < 0:
                raise GraphityStateError("Un pourcentage ne peut pas etre negatif.")
            normalized_targets.append({"runtime_revision_name": revision["name"], "percent": percent})

        state = self.load_state()
        state["traffic"] = {"mode": "manual", "targets": normalized_targets}
        self.save_state(state)

    def latest_revision(self) -> dict[str, Any]:
        self.ensure_bootstrap()
        revisions = self.load_state().get("revisions", [])
        if not revisions:
            raise GraphityStateError("Aucune revision Graphity.")
        return revisions[-1]

    def resolve_revision(self, key: str) -> dict[str, Any] | None:
        state = self.load_state()
        cleaned = key.strip()
        for revision in state.get("revisions", []):
            candidates = {
                str(revision.get("number")),
                str(revision.get("label")),
                str(revision.get("name")),
                str(revision.get("name", "")).split("/")[-1],
            }
            if cleaned in candidates:
                return revision
        return None

    def route_revision(self) -> dict[str, Any]:
        self.ensure_bootstrap()
        state = self.load_state()
        traffic = state.get("traffic", {})
        if traffic.get("mode") != "manual":
            return self.latest_revision()

        roll = random.randint(1, 100)
        cursor = 0
        for target in traffic.get("targets", []):
            cursor += int(target.get("percent", 0))
            if roll <= cursor:
                revision = self.resolve_revision(str(target.get("runtime_revision_name", "")))
                if revision:
                    return revision
        return self.latest_revision()

    def invoke(
        self,
        user_text: str,
        executor: Callable[[dict[str, Any], str], str],
    ) -> InvocationResult:
        revision = self.route_revision()
        graph_context = self.memory.recall(user_text)
        response = executor(revision, graph_context)
        return InvocationResult(
            revision_name=str(revision["name"]),
            revision_label=str(revision["label"]),
            response=response,
        )
```

Note de conception : `invoke()` n'écrit plus automatiquement en mémoire à
chaque tour (contrairement à l'ancien `GraphityMemory`). Écrire dans le
vault déclenche un `graphify update` (reconstruction du graphe) qui serait
bien trop coûteux à lancer à chaque message. L'écriture reste explicite,
via l'outil `graphity_remember` (Task 8).

- [ ] **Step 4: Vérifier que tous les tests passent**

Run:

```powershell
python -m pytest tests/test_graphity_runtime.py -v
```

Expected: 9 passed.

- [ ] **Step 5: Lancer toute la suite pour vérifier l'absence de régression**

Run:

```powershell
python -m pytest -v
```

Expected: 26 passed (11 de `test_vault_memory.py` + 9 de
`test_graphity_runtime.py` + 6 de `test_jarvis_agentic.py`, ce dernier
cree par la spec separee de robustesse de la boucle agentic, deja presente
sur cette branche).

- [ ] **Step 6: Commit**

```powershell
git add jarvis-starter/graphity_runtime.py jarvis-starter/tests/test_graphity_runtime.py
git commit -m "refactor: back GraphityRuntime with VaultMemory instead of the local toy engine"
```

---

### Task 5: Corriger `graphity_cli.py` (cassé par le nouveau constructeur)

**Files:**
- Modify: `jarvis-starter/graphity_cli.py`

Ce fichier appelle `GraphityRuntime(Path(args.data_dir))` (un seul
argument) et `runtime.memory.recent_context(...)` — les deux cassent avec
le nouveau `GraphityRuntime`/`VaultMemory`. Ni l'une ni l'autre spec ne
mentionnait ce fichier ; découvert par `grep` pendant la planification.

- [ ] **Step 1: Modifier `build_runtime` et l'import**

Dans `jarvis-starter/graphity_cli.py`, remplacer :

```python
from graphity_runtime import GraphityRuntime, GraphityStateError
```

par :

```python
from graphity_runtime import GraphityRuntime, GraphityStateError
from vault_memory import DEFAULT_VAULT_PATH
```

Remplacer :

```python
def build_runtime(args: argparse.Namespace) -> GraphityRuntime:
    return GraphityRuntime(Path(args.data_dir))
```

par :

```python
def build_runtime(args: argparse.Namespace) -> GraphityRuntime:
    return GraphityRuntime(Path(args.data_dir), Path(args.vault_path))
```

- [ ] **Step 2: Ajouter l'argument `--vault-path`**

Dans `jarvis-starter/graphity_cli.py`, après la ligne
`parser.add_argument("--data-dir", ...)`, ajouter :

```python
    parser.add_argument("--vault-path", default=DEFAULT_VAULT_PATH, help="Chemin du vault Obsidian.")
```

- [ ] **Step 3: Corriger la commande `recall`**

Remplacer :

```python
        elif args.command == "recall":
            print(runtime.memory.recent_context(args.query) or "Aucune memoire.")
```

par :

```python
        elif args.command == "recall":
            print(runtime.memory.recall(args.query))
```

- [ ] **Step 4: Vérifier que le script s'exécute sans erreur**

Run (depuis `jarvis-starter/`, dans un dossier temporaire pour ne pas
toucher le vault réel) :

```powershell
python graphity_cli.py --data-dir .\data\graphity-cli-test --vault-path .\data\fake-vault init
python graphity_cli.py --data-dir .\data\graphity-cli-test list
```

Expected: `Graphity initialise.` puis la liste des deux revisions, aucune
`TypeError`/`AttributeError`.

- [ ] **Step 5: Nettoyer le dossier de test**

Run:

```powershell
Remove-Item -Recurse -Force .\data\graphity-cli-test
```

- [ ] **Step 6: Commit**

```powershell
git add jarvis-starter/graphity_cli.py
git commit -m "fix: update graphity_cli.py for the VaultMemory-backed GraphityRuntime"
```

---

### Task 6: Instancier `GraphityRuntime` dans `jarvis.py`

**Files:**
- Modify: `jarvis-starter/jarvis.py:96-130` (Config/Jarvis init), `:734-751` (`main`)
- Modify: `jarvis-starter/env.template`

- [ ] **Step 1: Importer `DEFAULT_VAULT_PATH`**

Dans `jarvis-starter/jarvis.py`, la ligne d'import existante :

```python
from graphity_runtime import GraphityRuntime, GraphityStateError
```

devient :

```python
from graphity_runtime import GraphityRuntime, GraphityStateError
from vault_memory import DEFAULT_VAULT_PATH
```

- [ ] **Step 2: Ajouter `vault_path` au constructeur de `Jarvis`**

Remplacer (vers la ligne 468) :

```python
class Jarvis:
    def __init__(self, config: Config, voice: bool, data_dir: Path) -> None:
        self.config = config
        self.listener = Listener(voice=voice)
        self.speaker = Speaker(enabled=voice, name=config.assistant_name)
        self.memory = Memory(data_dir)
        self.ai = build_ai_client()
        self.pending_command: str | None = None
```

par :

```python
class Jarvis:
    def __init__(self, config: Config, voice: bool, data_dir: Path, vault_path: Path) -> None:
        self.config = config
        self.listener = Listener(voice=voice)
        self.speaker = Speaker(enabled=voice, name=config.assistant_name)
        self.memory = Memory(data_dir)
        self.ai = build_ai_client()
        self.graphity = GraphityRuntime(data_dir / "graphity", vault_path)
        self.pending_command: str | None = None
```

- [ ] **Step 3: Passer `vault_path` depuis `main()`**

Remplacer (vers la ligne 734) :

```python
def main(argv: list[str]) -> int:
    base_dir = Path(__file__).resolve().parent
    load_env_file(base_dir / ".env")

    args = parse_args(argv)
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = base_dir / config_path

    config = load_config(config_path)
    data_dir = Path(os.environ.get("JARVIS_DATA_DIR", base_dir / "data"))
    if not data_dir.is_absolute():
        data_dir = base_dir / data_dir

    voice = bool(args.voice and not args.text)
    app = Jarvis(config=config, voice=voice, data_dir=data_dir)
    app.run()
    return 0
```

par :

```python
def main(argv: list[str]) -> int:
    base_dir = Path(__file__).resolve().parent
    load_env_file(base_dir / ".env")

    args = parse_args(argv)
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = base_dir / config_path

    config = load_config(config_path)
    data_dir = Path(os.environ.get("JARVIS_DATA_DIR", base_dir / "data"))
    if not data_dir.is_absolute():
        data_dir = base_dir / data_dir

    vault_path = Path(os.environ.get("JARVIS_VAULT_PATH", "").strip() or DEFAULT_VAULT_PATH)

    voice = bool(args.voice and not args.text)
    app = Jarvis(config=config, voice=voice, data_dir=data_dir, vault_path=vault_path)
    app.run()
    return 0
```

- [ ] **Step 4: Ajouter la variable au template d'environnement**

Ajouter à la fin de `jarvis-starter/env.template` :

```env

# Chemin du vault Obsidian pour la memoire long terme (vide = valeur par
# defaut C:\Users\aiell\Documents\STARBOXE-Notes)
JARVIS_VAULT_PATH=
```

- [ ] **Step 5: Vérifier que Jarvis démarre toujours**

Run (depuis `jarvis-starter/`) :

```powershell
echo aide | python jarvis.py --text
```

Expected: affiche le message de bienvenue puis `HELP_TEXT`, aucune
exception au démarrage (confirme que `GraphityRuntime` s'instancie sans
erreur même si le vault par défaut existe mais n'est pas encore indexé).

- [ ] **Step 6: Commit**

```powershell
git add jarvis-starter/jarvis.py jarvis-starter/env.template
git commit -m "feat: instantiate GraphityRuntime with the configured vault path"
```

---

### Task 7: Router `run_agentic` via `GraphityRuntime.invoke()`

**Files:**
- Modify: `jarvis-starter/jarvis.py:576-607` (`run_agentic`)

- [ ] **Step 1: Réécrire `run_agentic`**

**Contexte important :** entre l'écriture initiale de ce plan et son
exécution, une spec séparée (`2026-07-11-agentic-loop-robustness-design.md`)
a corrigé un bug réel observé en conditions réelles : la boucle à 3 tours
sans déduplication faisait boucler le planificateur sur des appels d'outils
identiques sans jamais conclure. `run_agentic` sur cette branche a donc
déjà : une limite de **6** tours (pas 3), une déduplication des appels
d'outils identiques (`seen_calls`), et une méthode séparée
`force_final_synthesis` appelée en bout de boucle au lieu du dump
technique brut. Ce Step reprend cette version à jour comme base — ne pas
réintroduire l'ancienne boucle à 3 tours sans déduplication.

Remplacer la méthode `run_agentic` actuelle (vérifier qu'elle correspond
bien à la version ci-dessous avant de remplacer — sinon `git diff` d'abord
pour voir l'état réel du fichier) :

```python
    def run_agentic(self, user_text: str) -> str:
        if not self.ai.enabled:
            return LOCAL_ONLY_MESSAGE

        observations: list[str] = []
        seen_calls: set[str] = set()
        for _ in range(6):
            prompt = self.build_agent_prompt(user_text, observations)
            raw_answer = self.ai.ask(prompt, instructions=AGENTIC_SYSTEM_INSTRUCTIONS)
            payload = extract_json_object(raw_answer)
            if payload is None:
                return raw_answer

            tool_calls = payload.get("tool_calls", [])
            final = as_text(payload.get("final"))

            if not isinstance(tool_calls, list) or not tool_calls:
                return final or "Termine."

            for call in tool_calls[:5]:
                if not isinstance(call, dict):
                    observations.append("Appel outil ignore: format invalide.")
                    continue
                tool_name = as_text(call.get("tool"))
                args = call.get("args", {})
                if not isinstance(args, dict):
                    args = {}

                signature = f"{tool_name}:{json.dumps(args, sort_keys=True, ensure_ascii=False)}"
                if signature in seen_calls:
                    observations.append(
                        f"{tool_name}: deja execute avec ces arguments, resultat inchange. "
                        "N'appelle pas le meme outil avec les memes arguments deux fois."
                    )
                    continue
                seen_calls.add(signature)
                observations.append(self.execute_agent_tool(tool_name, args))

            if final:
                observations.append(f"Message provisoire du planificateur: {final}")

        return self.force_final_synthesis(user_text, observations)
```

par :

```python
    def run_agentic(self, user_text: str) -> str:
        if not self.ai.enabled:
            return LOCAL_ONLY_MESSAGE

        def executor(revision: dict[str, Any], graph_context: str) -> str:
            instructions = f"{revision['instructions']}\n\n{AGENTIC_SYSTEM_INSTRUCTIONS}"
            observations: list[str] = []
            seen_calls: set[str] = set()
            if graph_context and "vault_memory:" not in graph_context:
                observations.append(f"Contexte du vault (memoire long terme):\n{graph_context}")

            for _ in range(6):
                prompt = self.build_agent_prompt(user_text, observations)
                raw_answer = self.ai.ask(prompt, instructions=instructions)
                payload = extract_json_object(raw_answer)
                if payload is None:
                    return raw_answer

                tool_calls = payload.get("tool_calls", [])
                final = as_text(payload.get("final"))

                if not isinstance(tool_calls, list) or not tool_calls:
                    return final or "Termine."

                for call in tool_calls[:5]:
                    if not isinstance(call, dict):
                        observations.append("Appel outil ignore: format invalide.")
                        continue
                    tool_name = as_text(call.get("tool"))
                    args = call.get("args", {})
                    if not isinstance(args, dict):
                        args = {}

                    signature = f"{tool_name}:{json.dumps(args, sort_keys=True, ensure_ascii=False)}"
                    if signature in seen_calls:
                        observations.append(
                            f"{tool_name}: deja execute avec ces arguments, resultat inchange. "
                            "N'appelle pas le meme outil avec les memes arguments deux fois."
                        )
                        continue
                    seen_calls.add(signature)
                    observations.append(self.execute_agent_tool(tool_name, args))

                if final:
                    observations.append(f"Message provisoire du planificateur: {final}")

            return self.force_final_synthesis(user_text, observations)

        result = self.graphity.invoke(user_text, executor)
        return result.response
```

Note : `force_final_synthesis` reste une méthode séparée sur `Jarvis`,
inchangée par ce plan — elle est appelée telle quelle depuis l'intérieur
de `executor`.

- [ ] **Step 2: Vérifier manuellement (sans clé IA, doit rester inchangé)**

Run :

```powershell
echo agent quelle heure est-il | python jarvis.py --text
```

Expected: message `LOCAL_ONLY_MESSAGE` (aucune clé IA configurée dans cet
environnement de test), confirmant que le nouveau chemin ne casse pas le
cas sans IA.

- [ ] **Step 3: Commit**

```powershell
git add jarvis-starter/jarvis.py
git commit -m "feat: route run_agentic through GraphityRuntime.invoke for revision + vault context"
```

---

### Task 8: Câbler les commandes directes `graphity *`

**Files:**
- Modify: `jarvis-starter/jarvis.py:518-574` (`handle`)

- [ ] **Step 1: Ajouter la branche `graphity ` dans `handle()`**

Dans `jarvis-starter/jarvis.py`, insérer après le bloc `if command.startswith("agent "):` (juste avant `if command.startswith("cherche "):`) :

```python
        if command.startswith("graphity "):
            self.speaker.say(self.run_graphity_command(cleaned_text.split(" ", 1)[1].strip()))
            return True
```

- [ ] **Step 2: Ajouter les méthodes `run_graphity_command` et `parse_split_targets`**

Ajouter ces deux méthodes à la classe `Jarvis` (par exemple juste après
`run_agentic`) :

```python
    def run_graphity_command(self, sub_command: str) -> str:
        normalized = normalize(sub_command)

        if normalized == "revisions":
            revisions = self.graphity.list_revisions()
            lines = [f"{r['number']}. {r['label']} ({r['agent_kind']})" for r in revisions]
            return "\n".join(lines) if lines else "Aucune revision."

        if normalized == "traffic":
            return self.graphity.describe_traffic()

        if normalized == "latest":
            self.graphity.set_always_latest()
            return "Traffic route vers la derniere revision."

        if normalized.startswith("split "):
            targets_text = sub_command.split(" ", 1)[1].strip()
            try:
                targets = self.parse_split_targets(targets_text)
                self.graphity.set_manual_split(targets)
            except GraphityStateError as exc:
                return f"graphity split: {exc}"
            return f"Split applique: {targets_text}"

        if normalized.startswith("memo "):
            query = sub_command.split(" ", 1)[1].strip()
            if not query:
                return "graphity memo: requete manquante."
            return self.graphity.memory.recall(query)

        return "Sous-commande graphity inconnue. Essaie: revisions, traffic, split, latest, memo."

    def parse_split_targets(self, text: str) -> dict[str, int]:
        targets: dict[str, int] = {}
        for chunk in text.split():
            if "=" not in chunk:
                raise GraphityStateError(f"Format invalide: {chunk} (attendu cle=valeur)")
            key, value = chunk.split("=", 1)
            key = key.strip()
            try:
                percent = int(value.strip())
            except ValueError:
                raise GraphityStateError(f"Pourcentage invalide: {value}") from None
            targets[key] = percent
        return targets
```

- [ ] **Step 3: Vérifier manuellement**

Run :

```powershell
printf "graphity revisions\ngraphity traffic\ngraphity split 1=50 2=50\ngraphity traffic\ngraphity latest\nquitte\n" | python jarvis.py --text
```

Expected : liste des 2 revisions, `always_latest -> v2-graph-memory (2)`,
`Split applique: 1=50 2=50`, `manual split:\n- 50% -> v1-fast-local\n- 50%
-> v2-graph-memory`, `Traffic route vers la derniere revision.` — plus
aucun de ces messages n'était produit avant ce plan (code mort).

- [ ] **Step 4: Commit**

```powershell
git add jarvis-starter/jarvis.py
git commit -m "feat: wire up the graphity revisions/traffic/split/latest/memo commands"
```

---

### Task 9: Câbler les outils agentic `graphity_recall`/`graphity_remember`

**Files:**
- Modify: `jarvis-starter/jarvis.py:636-672` (`execute_agent_tool`)

- [ ] **Step 1: Ajouter les deux branches d'outil**

Dans `jarvis-starter/jarvis.py`, méthode `execute_agent_tool`, insérer
avant la ligne finale `return f"{tool_name}: outil non autorise."` :

```python
        if tool_name == "graphity_recall":
            query = as_text(args.get("query"))
            if not query:
                return "graphity_recall: requete manquante."
            return "graphity_recall: " + self.graphity.memory.recall(query)

        if tool_name == "graphity_remember":
            text = as_text(args.get("text"))
            if not text:
                return "graphity_remember: texte manquant."
            return "graphity_remember: " + self.graphity.memory.remember(text)
```

- [ ] **Step 2: Vérifier via un appel direct à `execute_agent_tool`**

Run un script ponctuel (depuis `jarvis-starter/`) :

```powershell
python -c "from jarvis import Jarvis, load_config; from pathlib import Path; j = Jarvis(load_config(Path('config.json')), False, Path('data'), Path('data/fake-vault')); print(j.execute_agent_tool('graphity_recall', {'query': 'test'}))"
```

Expected: `graphity_recall: vault_memory: vault introuvable a data\fake-vault`
(le vault de test n'existe pas — confirme que la branche est bien câblée
et gère l'erreur proprement plutôt que de renvoyer "outil non autorise.").

- [ ] **Step 3: Commit**

```powershell
git add jarvis-starter/jarvis.py
git commit -m "feat: wire up graphity_recall and graphity_remember agentic tools"
```

---

### Task 10: Documentation README

**Files:**
- Modify: `jarvis-starter/README.md`

- [ ] **Step 1: Ajouter une section mémoire vault**

Ajouter avant la section `## Architecture reelle` de
`jarvis-starter/README.md` :

`````markdown
## Memoire long terme (vault Obsidian)

Jarvis peut memoriser des faits durables directement dans ton vault
Obsidian et les rappeler via le vrai graphe de connaissances `graphify`
(pas un index maison).

1. Installe `graphify` si necessaire (`npm install -g graphify`).
2. Dans `.env`, configure `JARVIS_VAULT_PATH` si ton vault n'est pas
   `C:\Users\aiell\Documents\STARBOXE-Notes` (valeur par defaut).
3. Utilise:

```text
graphity memo campagne SEO
agent souviens-toi que je dois relancer la campagne SEO en aout
```

Les notes de Jarvis s'ecrivent dans `<vault>/04_Agents_IA/Jarvis/` et
declenchent une reconstruction du graphe (`graphify update`) a chaque
ecriture.

## Revisions Jarvis (A/B)

Chaque demande agentic est routee entre deux personas : `v1-fast-local`
(reponses courtes, outils seulement si utiles) et `v2-graph-memory`
(privilegie la memoire du vault). Par defaut, toujours la derniere
revision creee.

```text
graphity revisions
graphity traffic
graphity split 1=50 2=50
graphity latest
```
`````

- [ ] **Step 2: Ajouter une section tests**

Ajouter avant la section `## Architecture reelle` (après la section
mémoire ajoutée au Step 1) :

`````markdown
## Lancer les tests

```powershell
pip install -r requirements-dev.txt
python -m pytest
```
`````

- [ ] **Step 3: Commit**

```powershell
git add jarvis-starter/README.md
git commit -m "docs: document vault memory, graphity revisions, and tests"
```

---

### Task 11: Vérification end-to-end et récapitulatif

**Files:** aucun changement de code — validation uniquement.

- [ ] **Step 1: Lancer toute la suite de tests**

Run (depuis `jarvis-starter/`) :

```powershell
python -m pytest -v
```

Expected: 26 passed, 0 failed.

- [ ] **Step 2: Test manuel bout-en-bout contre le vrai vault**

Run :

```powershell
printf "graphity memo test\nagent souviens-toi que le plan vault memory a ete implemente le 11 juillet\ngraphity memo plan vault\nquitte\n" | python jarvis.py --text
```

Expected: la premiere commande retourne soit un resultat du graphe soit
`"vault_memory: graphe absent..."` si `.graphify/graph.json` n'existe pas
encore dans le vault reel ; la commande `agent` (sans IA configuree dans
cet environnement) retourne `LOCAL_ONLY_MESSAGE` (comportement attendu
sans cle) ; verifie manuellement qu'aucune exception Python n'apparait.

- [ ] **Step 3: Vérifier qu'un fichier a bien ete cree dans le vault (si le
  test precedent avait une IA active) ou documenter que ce test necessite
  une cle IA pour couvrir `graphity_remember` de bout en bout**

Run :

```powershell
Get-ChildItem "C:\Users\aiell\Documents\STARBOXE-Notes\04_Agents_IA\Jarvis" -ErrorAction SilentlyContinue
```

Expected: dossier absent si aucune IA n'a ete configuree pendant ce test
(aucun appel a `graphity_remember` n'a pu se produire sans planificateur
LLM) — normal, pas un echec. Note pour l'utilisateur : pour valider
`graphity_remember` en conditions reelles, configurer `OPENAI_API_KEY` ou
`OLLAMA_MODEL` puis relancer `agent souviens-toi que ...`.

- [ ] **Step 4: Commit final si des ajustements ont ete faits**

```powershell
git status --short
```

Si des fichiers non commit apparaissent (ajustements pendant la
verification), les committer un par un avec un message decrivant
precisement la correction.
