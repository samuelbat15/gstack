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
        monkeypatch.setattr("vault_memory._graphify_executable", lambda: "graphify")
        result = memory.remember("il faut relancer la campagne SEO")

        assert "enregistree" in result
        notes = list((tmp_path / "04_Agents_IA" / "Jarvis").glob("*.md"))
        assert len(notes) == 1
        assert "relancer la campagne SEO" in notes[0].read_text(encoding="utf-8")
        assert calls == [["graphify", "update", str(tmp_path)]]

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