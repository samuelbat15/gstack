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


import anyio
import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from vault_memory import DEFAULT_VAULT_PATH

server: Server = Server("graphify")

_runtime: GraphityRuntime | None = None


def _get_runtime() -> GraphityRuntime:
    if _runtime is None:
        raise RuntimeError("graphify_mcp_server: runtime not initialized, call main() first")
    return _runtime


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="graphify_recall",
            description=(
                "Recall information from the Obsidian vault's Graphify "
                "knowledge graph for a given query or topic."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The question or topic to search for.",
                    },
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="graphify_remember",
            description=(
                "Record a durable fact or note into the Obsidian vault, "
                "to be indexed into the Graphify knowledge graph."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The fact or note text to remember.",
                    },
                },
                "required": ["text"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    result = dispatch_tool_call(_get_runtime(), name, arguments)
    return [types.TextContent(type="text", text=result)]


async def _run() -> None:
    global _runtime
    vault_path = Path(DEFAULT_VAULT_PATH)
    validate_vault(vault_path)
    _runtime = GraphityRuntime(DEFAULT_DATA_DIR, vault_path)

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    anyio.run(_run)


if __name__ == "__main__":
    main()
