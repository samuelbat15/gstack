from __future__ import annotations

from pathlib import Path
from typing import Any

from graphity_runtime import GraphityRuntime

DEFAULT_DATA_DIR = Path(__file__).resolve().parent / "data" / "graphify-mcp"


class VaultNotFoundError(ValueError):
    """Raised when the configured vault path or its .graphify index is missing."""


def validate_vault(vault_path: Path) -> None:
    """Fail fast if the vault or its Graphify index doesn't exist.

    Without a real, indexed vault this server has no reason to run --
    every call would just return "graphe absent" from vault_memory.py.
    """
    if not vault_path.is_dir():
        raise VaultNotFoundError(f"vault introuvable: {vault_path}")
    graph_path = vault_path / ".graphify" / "graph.json"
    if not graph_path.is_file():
        raise VaultNotFoundError(
            f"vault trouve mais non indexe (pas de {graph_path}): "
            f"lance 'graphify {vault_path}' pour l'indexer"
        )


def dispatch_tool_call(
    runtime: GraphityRuntime, tool_name: str, arguments: dict[str, Any]
) -> str:
    """Route an MCP tool call to the underlying GraphityRuntime.memory.

    Never raises for tool-internal failures (vault_memory.py already
    returns explanatory error strings for those, e.g. "graphe absent",
    "graphify introuvable dans le PATH") -- only raises ValueError for a
    genuinely malformed call (unknown tool name, missing required arg),
    which is a caller bug, not a runtime condition to report as text.
    """
    if tool_name == "graphify_recall":
        query = arguments.get("query")
        if not query:
            raise ValueError("graphify_recall: 'query' argument is required")
        return runtime.memory.recall(str(query))

    if tool_name == "graphify_remember":
        text = arguments.get("text")
        if not text:
            raise ValueError("graphify_remember: 'text' argument is required")
        return runtime.memory.remember(str(text))

    raise ValueError(f"unknown tool: {tool_name}")
