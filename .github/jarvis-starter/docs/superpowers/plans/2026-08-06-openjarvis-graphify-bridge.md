# OpenJarvis Graphify MCP Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose `jarvis-starter`'s existing Graphify knowledge graph (51k nodes on the STARBOXE-Notes Obsidian vault) to OpenJarvis as two MCP tools (`graphify_recall`, `graphify_remember`), so OpenJarvis's agent can use it without any changes to OpenJarvis's installed source.

**Architecture:** A new standalone stdio MCP server (`graphify_mcp_server.py`) that wraps the existing `GraphityRuntime`/`VaultMemory` classes unchanged, registered in OpenJarvis via its native `[tools.mcp]` config (`command`/`args`, `StdioTransport`). Split into two tasks: pure, easily-testable handler logic first, then the thin async MCP-SDK wiring on top.

**Tech Stack:** Python (same interpreter as `jarvis.py` — Anaconda, confirmed via `which python`), `mcp` SDK (official Model Context Protocol Python package, already installed at `C:\Users\aiell\AppData\Local\Programs\Python\Python312\Lib\site-packages` but NOT in the Anaconda env `jarvis-starter` actually runs on — Task 2 installs it there), `anyio` (mcp SDK's async runtime, ships as its dependency).

---

## Context for the engineer

`jarvis-starter` (`c:/Users/aiell/Projects/gstack/.github/jarvis-starter/`) already has a working knowledge-graph memory system:

- `graphity_runtime.py:48-54` — `GraphityRuntime(data_dir, vault_path)` constructs a `VaultMemory(vault_path)` instance at `self.memory`.
- `vault_memory.py:21-99` — `VaultMemory.recall(query) -> str` shells out to the `graphify` CLI (`graphify query <query> --graph <vault>/.graphify/graph.json`), returns the query result as text (or an explanatory error string — this class never raises). `VaultMemory.remember(text) -> str` writes a markdown note into the vault and fires a detached background `graphify update` (also never raises).
- `DEFAULT_VAULT_PATH = r"C:\Users\aiell\Documents\STARBOXE-Notes"` (`vault_memory.py:9`) — the real vault, already has a populated `.graphify/graph.json` (51008 nodes, verified working).

OpenJarvis (`C:/Users/aiell/Projects/OpenJarvis/`, cloned, installed via the official `install.ps1`) loads MCP tools per `src/openjarvis/mcp/loader.py:33-131`: `config.tools.mcp.servers` is a JSON-encoded list of `{"name": ..., "command": ..., "args": [...]}` objects; each becomes a `StdioTransport(command=[command] + args)`, wrapped in an `MCPClient`, tools auto-discovered via the standard MCP `initialize` → `tools/list` handshake.

You do not need to read either codebase further — the exact APIs you need are given in full below.

---

## Task 1: Pure handler logic + fail-fast vault validation

**Files:**
- Create: `c:/Users/aiell/Projects/gstack/.github/jarvis-starter/graphify_mcp_server.py`
- Test: `c:/Users/aiell/Projects/gstack/.github/jarvis-starter/tests/test_graphify_mcp_server.py`

This task builds the two functions that do the real work — `validate_vault` (fail-fast check) and `dispatch_tool_call` (the recall/remember logic) — as plain, synchronous, dependency-free functions. No MCP SDK involved yet, so these are fast and simple to test. Task 2 wires them into the actual MCP protocol.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_graphify_mcp_server.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest

from graphify_mcp_server import VaultNotFoundError, dispatch_tool_call, validate_vault
from graphity_runtime import GraphityRuntime
from vault_memory import DEFAULT_VAULT_PATH


class TestValidateVault:
    def test_raises_on_missing_vault(self, tmp_path):
        missing = tmp_path / "does-not-exist"
        with pytest.raises(VaultNotFoundError):
            validate_vault(missing)

    def test_raises_when_graphify_dir_missing(self, tmp_path):
        vault = tmp_path / "vault-without-graphify"
        vault.mkdir()
        with pytest.raises(VaultNotFoundError):
            validate_vault(vault)

    def test_passes_for_real_vault(self):
        # Real vault, verified earlier in this session to have a populated
        # .graphify/graph.json (51008 nodes). No exception should be raised.
        validate_vault(Path(DEFAULT_VAULT_PATH))


class TestDispatchToolCall:
    def test_unknown_tool_raises_value_error(self, tmp_path):
        runtime = GraphityRuntime(tmp_path / "data", tmp_path / "vault")
        with pytest.raises(ValueError, match="unknown tool"):
            dispatch_tool_call(runtime, "not_a_real_tool", {})

    def test_recall_missing_query_arg_raises_value_error(self, tmp_path):
        runtime = GraphityRuntime(tmp_path / "data", tmp_path / "vault")
        with pytest.raises(ValueError, match="query"):
            dispatch_tool_call(runtime, "graphify_recall", {})

    def test_remember_missing_text_arg_raises_value_error(self, tmp_path):
        runtime = GraphityRuntime(tmp_path / "data", tmp_path / "vault")
        with pytest.raises(ValueError, match="text"):
            dispatch_tool_call(runtime, "graphify_remember", {})

    def test_recall_against_real_vault_returns_real_content(self):
        # Real end-to-end call against the actual 51k-node graph, no mock.
        runtime = GraphityRuntime(
            Path(DEFAULT_VAULT_PATH).parent / "jarvis-graphify-mcp-test-data",
            Path(DEFAULT_VAULT_PATH),
        )
        result = dispatch_tool_call(
            runtime, "graphify_recall", {"query": "STARBOXE"}
        )
        assert result
        assert not result.startswith("vault_memory: graphe absent")
        assert not result.startswith("vault_memory: erreur")

    def test_remember_then_recall_round_trip(self, tmp_path, monkeypatch):
        # Uses a throwaway vault (tmp_path), not the real one, so this
        # doesn't write test notes into STARBOXE-Notes. graphify CLI must
        # be on PATH for this test to exercise the real remember() write
        # path (recall() against an empty/no-graph tmp vault will just
        # return the "graphe absent" message, which is fine here --
        # this test only checks that remember() itself doesn't raise and
        # that the note file lands on disk).
        vault = tmp_path / "throwaway-vault"
        vault.mkdir()
        runtime = GraphityRuntime(tmp_path / "data", vault)

        result = dispatch_tool_call(
            runtime, "graphify_remember", {"text": "test note from pytest"}
        )

        assert "enregistree" in result
        notes = list((vault / "04_Agents_IA" / "Jarvis").glob("*.md"))
        assert len(notes) == 1
        assert "test note from pytest" in notes[0].read_text(encoding="utf-8")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd c:/Users/aiell/Projects/gstack/.github/jarvis-starter && python -m pytest tests/test_graphify_mcp_server.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'graphify_mcp_server'` (7 errors — the module doesn't exist yet).

- [ ] **Step 3: Write the implementation**

Create `graphify_mcp_server.py`:

```python
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
    if not vault_path.exists():
        raise VaultNotFoundError(f"vault introuvable: {vault_path}")
    if not (vault_path / ".graphify").is_dir():
        raise VaultNotFoundError(
            f"vault trouve mais non indexe (pas de .graphify/): {vault_path}"
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd c:/Users/aiell/Projects/gstack/.github/jarvis-starter && python -m pytest tests/test_graphify_mcp_server.py -v`
Expected: PASS (7 passed). Note: `test_recall_against_real_vault_returns_real_content` and `test_remember_then_recall_round_trip` call the real `graphify` CLI — if `graphify` isn't on PATH in the environment running this, the recall test will still pass (vault_memory.py returns a `"graphify introuvable dans le PATH"` string, not a raised exception, and the assertions only check for `"graphe absent"`/`"erreur"` prefixes) but won't be exercising the real query path. Confirm `graphify` resolves (`shutil.which("graphify")` or `where graphify`) before treating this test as a meaningful check of the real graph.

- [ ] **Step 5: Commit**

```bash
cd c:/Users/aiell/Projects/gstack
git add .github/jarvis-starter/graphify_mcp_server.py .github/jarvis-starter/tests/test_graphify_mcp_server.py
git commit -m "feat(jarvis): add Graphify MCP bridge handler logic"
```

---

## Task 2: MCP server wiring + OpenJarvis config

**Files:**
- Modify: `c:/Users/aiell/Projects/gstack/.github/jarvis-starter/graphify_mcp_server.py` (append the MCP SDK wiring and `main()`)
- Modify: `c:/Users/aiell/Projects/gstack/.github/jarvis-starter/requirements.txt` (add `mcp`)
- Modify: `C:/Users/aiell/Projects/OpenJarvis/configs/openjarvis/config.toml` (register the server)

- [ ] **Step 1: Install the `mcp` SDK into the environment jarvis-starter actually runs on**

`jarvis-starter` runs under the Anaconda Python (confirmed via `which python` resolving to `/c/Users/aiell/anaconda3/python` in this environment — the same interpreter `launch_jarvis.bat` invokes via bare `python`). The `mcp` package is currently only installed under a *different* Python (3.12) on this machine, the same PATH-mismatch pattern already hit once before with `SpeechRecognition`/`pyttsx3`.

Run:
```powershell
python -m pip install "mcp>=1.27.0"
```
Expected: successful install, ending with `Successfully installed mcp-<version> ...` (plus its dependencies, e.g. `anyio`, `httpx`, `pydantic`, `sse-starlette` — these are the `mcp` package's own requirements, not something to hand-pick).

Verify: `python -c "import mcp; print(mcp.__version__)"` prints a version `>= 1.27.0` without raising `ModuleNotFoundError`.

- [ ] **Step 2: Add the dependency to `requirements.txt`**

In `c:/Users/aiell/Projects/gstack/.github/jarvis-starter/requirements.txt`, add a new section (matching the file's existing style of grouped, commented sections):

```
# MCP server: exposes graphify_recall/graphify_remember to OpenJarvis.
mcp>=1.27.0
```

- [ ] **Step 3: Append the MCP server wiring to `graphify_mcp_server.py`**

Append this to the end of `c:/Users/aiell/Projects/gstack/.github/jarvis-starter/graphify_mcp_server.py` (after the `dispatch_tool_call` function from Task 1):

```python
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
```

- [ ] **Step 4: Verify the server starts and speaks MCP correctly**

Run (from `jarvis-starter/`, this blocks waiting on stdin — send it a single MCP `initialize` request on stdin and confirm a well-formed JSON-RPC response comes back on stdout, then Ctrl+C):

```powershell
python -c "
import json, subprocess, sys
proc = subprocess.Popen(
    ['python', 'graphify_mcp_server.py'],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
)
request = {
    'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
    'params': {'protocolVersion': '2024-11-05', 'capabilities': {}, 'clientInfo': {'name': 'smoke-test', 'version': '0'}},
}
proc.stdin.write(json.dumps(request) + chr(10))
proc.stdin.flush()
line = proc.stdout.readline()
print('RESPONSE:', line)
proc.terminate()
"
```

Expected: a line starting `RESPONSE: {"jsonrpc": "2.0", "id": 1, "result": {...}}` containing `"serverInfo": {"name": "graphify", ...}`. If instead you see a traceback on stderr or nothing on stdout, the server failed to start — check `validate_vault` didn't raise (it shouldn't, the real vault exists) and that `mcp` imported correctly (Step 1).

- [ ] **Step 5: Register the server in OpenJarvis's config**

In `C:/Users/aiell/Projects/OpenJarvis/configs/openjarvis/config.toml`, find the existing section:

```toml
[tools.mcp]
enabled = true
```

Replace it with:

```toml
[tools.mcp]
enabled = true
servers = '''[{"name": "graphify", "command": "python", "args": ["c:/Users/aiell/Projects/gstack/.github/jarvis-starter/graphify_mcp_server.py"]}]'''
```

(The `servers` value is a JSON-encoded string per `src/openjarvis/mcp/loader.py:59-65` — it is parsed with `json.loads`, not read as native TOML, so it must stay a single-quoted/triple-quoted string containing valid JSON, not a TOML array of tables.)

- [ ] **Step 6: End-to-end verification against OpenJarvis itself**

From `C:/Users/aiell/Projects/OpenJarvis/`, start OpenJarvis (`jarvis`, per its README quick start) and ask a question whose answer requires the vault's graph content (e.g. something specific to STARBOXE that only exists in the vault, not general knowledge). Confirm:
1. OpenJarvis's agent invokes the `graphify_recall` tool (visible in its tool-call trace/logs).
2. The response reflects real content from the vault, not a generic/hallucinated answer.

This step has no fixed pass/fail assertion to paste here (it depends on OpenJarvis's actual runtime behavior, which the engineer running this plan should observe directly) — but it is not optional. A test suite passing without agent traffic can't be documented in advance; watch the actual agent turn happen.

- [ ] **Step 7: Commit**

```bash
cd c:/Users/aiell/Projects/gstack
git add .github/jarvis-starter/graphify_mcp_server.py .github/jarvis-starter/requirements.txt
git commit -m "feat(jarvis): wire Graphify MCP server + register with OpenJarvis"
```

Note: `config.toml` lives in the separate `OpenJarvis` repo (`C:/Users/aiell/Projects/OpenJarvis/`), not in `gstack` — commit it there separately if that repo's own workflow calls for it (check `git -C C:/Users/aiell/Projects/OpenJarvis status` first; this plan does not assume anything about that repo's commit conventions since it's third-party, upstream code we're only locally configuring).

---

## Self-review notes (already applied above)

- **Spec coverage:** architecture (standalone MCP server, no OpenJarvis source edits) — Task 2 Step 5 uses only config, confirmed. Reuse of `graphity_runtime.py`/`vault_memory.py` unchanged — confirmed, `dispatch_tool_call` only calls `runtime.memory.recall`/`remember`, never reimplements them. Fail-fast on missing vault — `validate_vault`, tested in Task 1. Error handling (server never crashes on a bad call) — `dispatch_tool_call` only raises on genuinely malformed calls (per spec's own error-handling section), tool-internal failures stay as returned strings exactly as `vault_memory.py` already produces them. Tests including one real, non-mocked check — `test_recall_against_real_vault_returns_real_content`. End-to-end verification — Task 2 Step 6.
- **Placeholder scan:** none — every step has complete, runnable code or an exact command with a stated expected result.
- **Type consistency:** `dispatch_tool_call(runtime: GraphityRuntime, tool_name: str, arguments: dict[str, Any]) -> str` is defined once in Task 1 and called identically (`dispatch_tool_call(_get_runtime(), name, arguments)`) in Task 2 — no signature drift. `validate_vault(vault_path: Path) -> None` likewise used identically in both the Task 1 tests and Task 2's `_run()`.
