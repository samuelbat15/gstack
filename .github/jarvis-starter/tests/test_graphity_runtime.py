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
