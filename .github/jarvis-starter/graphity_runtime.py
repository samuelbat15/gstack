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
        self.ensure_bootstrap()
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
