from __future__ import annotations

import hashlib
import json
import random
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


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


def normalize_key(text: str) -> str:
    return " ".join(text.casefold().strip().split())


class GraphityMemory:
    stopwords = {
        "avec",
        "dans",
        "donc",
        "elle",
        "pour",
        "quoi",
        "sont",
        "tout",
        "une",
        "vous",
        "that",
        "this",
        "from",
        "have",
        "what",
        "when",
        "your",
        "the",
        "and",
        "les",
        "des",
        "que",
        "qui",
        "sur",
        "est",
    }

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.events_path = data_dir / "events.jsonl"
        self.graph_path = data_dir / "graph.json"
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def remember(self, role: str, content: str, revision_name: str = "manual") -> None:
        content = content.strip()
        if not content:
            return

        event = {
            "id": str(uuid.uuid4()),
            "created_at": now_iso(),
            "revision_name": revision_name,
            "role": role,
            "content": content,
            "entities": self.extract_entities(content),
        }
        with self.events_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(event, ensure_ascii=False) + "\n")
        self.update_graph(event)

    def recent_context(self, query: str, limit: int = 8) -> str:
        events = self.load_events()
        if not events:
            return ""

        query_entities = set(self.extract_entities(query))
        scored: list[tuple[int, dict[str, Any]]] = []
        for index, event in enumerate(events):
            event_entities = set(event.get("entities", []))
            score = len(query_entities & event_entities)
            recency_bonus = 1 if index >= max(0, len(events) - limit) else 0
            if score or recency_bonus:
                scored.append((score * 10 + recency_bonus, event))

        selected = [event for _, event in sorted(scored, key=lambda item: item[0], reverse=True)[:limit]]
        if not selected:
            selected = events[-limit:]

        lines = []
        for event in selected:
            role = event.get("role", "event")
            content = event.get("content", "")
            created_at = event.get("created_at", "")
            lines.append(f"- {created_at} {role}: {content}")
        return "\n".join(lines)

    def load_events(self) -> list[dict[str, Any]]:
        if not self.events_path.exists():
            return []

        events: list[dict[str, Any]] = []
        for line in self.events_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                events.append(payload)
        return events

    def extract_entities(self, text: str) -> list[str]:
        words = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9][A-Za-zÀ-ÖØ-öø-ÿ0-9_-]{2,}", text)
        entities: list[str] = []
        for word in words:
            key = normalize_key(word)
            if key in self.stopwords:
                continue
            if key not in entities:
                entities.append(key)
        return entities[:24]

    def update_graph(self, event: dict[str, Any]) -> None:
        graph = read_json(self.graph_path, {"nodes": {}, "edges": []})
        nodes = graph.setdefault("nodes", {})
        edges = graph.setdefault("edges", [])

        revision_name = str(event.get("revision_name", "manual"))
        revision_node = f"revision:{revision_name}"
        nodes.setdefault(revision_node, {"type": "revision", "label": revision_name, "count": 0})
        nodes[revision_node]["count"] += 1

        for entity in event.get("entities", []):
            entity_node = f"entity:{entity}"
            nodes.setdefault(entity_node, {"type": "entity", "label": entity, "count": 0})
            nodes[entity_node]["count"] += 1
            edges.append(
                {
                    "source": revision_node,
                    "target": entity_node,
                    "type": "mentioned",
                    "created_at": event.get("created_at", now_iso()),
                }
            )

        graph["edges"] = edges[-1000:]
        write_json(self.graph_path, graph)


class GraphityRuntime:
    def __init__(self, data_dir: Path, engine_name: str = DEFAULT_ENGINE_NAME) -> None:
        self.data_dir = data_dir
        self.state_path = data_dir / "state.json"
        self.memory = GraphityMemory(data_dir / "memory")
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
        revision_name = str(revision["name"])
        self.memory.remember("user", user_text, revision_name)
        graph_context = self.memory.recent_context(user_text)
        response = executor(revision, graph_context)
        self.memory.remember("assistant", response, revision_name)
        return InvocationResult(
            revision_name=revision_name,
            revision_label=str(revision["label"]),
            response=response,
        )
