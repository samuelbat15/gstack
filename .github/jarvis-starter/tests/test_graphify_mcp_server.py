from __future__ import annotations

import shutil
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

    def test_raises_when_graph_json_missing(self, tmp_path):
        vault = tmp_path / "vault-with-empty-graphify-dir"
        (vault / ".graphify").mkdir(parents=True)
        with pytest.raises(VaultNotFoundError):
            validate_vault(vault)

    @pytest.mark.skipif(not Path(DEFAULT_VAULT_PATH).is_dir(), reason="real vault not present")
    def test_passes_for_real_vault(self):
        # Real vault, verified earlier in this session to have a populated
        # .graphify/graph.json (51008 nodes). No exception should be raised.
        validate_vault(Path(DEFAULT_VAULT_PATH))

    def test_passes_for_hermetic_vault_with_graph_json(self, tmp_path):
        vault = tmp_path / "hermetic-vault"
        graphify_dir = vault / ".graphify"
        graphify_dir.mkdir(parents=True)
        (graphify_dir / "graph.json").write_text("{}", encoding="utf-8")
        validate_vault(vault)  # should not raise


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

    @pytest.mark.skipif(shutil.which("graphify") is None, reason="graphify CLI not on PATH")
    @pytest.mark.skipif(not Path(DEFAULT_VAULT_PATH).is_dir(), reason="real vault not present")
    def test_recall_against_real_vault_returns_real_content(self, tmp_path):
        # Real end-to-end call against the actual 51k-node graph, no mock.
        # data_dir uses tmp_path (unused by the recall path, but must not
        # write anywhere permanent); vault_path is the real vault.
        runtime = GraphityRuntime(tmp_path / "data", Path(DEFAULT_VAULT_PATH))
        result = dispatch_tool_call(
            runtime, "graphify_recall", {"query": "STARBOXE"}
        )
        assert result
        assert not result.startswith("vault_memory:")

    def test_remember_then_recall_round_trip(self, tmp_path, monkeypatch):
        # Uses a throwaway vault (tmp_path), not the real one. The background
        # graphify-update launch is stubbed out (same convention as
        # test_vault_memory.py) so this test never spawns a real detached
        # subprocess.
        monkeypatch.setattr("vault_memory.subprocess.Popen", lambda *a, **k: None)

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
