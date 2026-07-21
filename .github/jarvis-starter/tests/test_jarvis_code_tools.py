from __future__ import annotations

from pathlib import Path

from jarvis import Config, Jarvis, looks_like_local_command


def make_jarvis(tmp_path, confirm_actions=False, confirm_fn=None):
    config = Config(assistant_name="Jarvis", confirm_actions=confirm_actions, sites={}, apps={})
    return Jarvis(
        config=config,
        voice=False,
        data_dir=tmp_path,
        vault_path=tmp_path / "vault",
        confirm_fn=confirm_fn,
    )


class TestWriteFile:
    def test_writes_file_content(self, tmp_path):
        jarvis = make_jarvis(tmp_path)
        target = tmp_path / "hello.py"

        result = jarvis.write_file(str(target), "print('hello')")

        assert target.read_text(encoding="utf-8") == "print('hello')"
        assert "fichier ecrit" in result
        assert str(target) in result

    def test_creates_parent_directories(self, tmp_path):
        jarvis = make_jarvis(tmp_path)
        target = tmp_path / "sub" / "dir" / "hello.py"

        jarvis.write_file(str(target), "x = 1")

        assert target.read_text(encoding="utf-8") == "x = 1"

    def test_refused_by_user_does_not_write(self, tmp_path):
        jarvis = make_jarvis(tmp_path, confirm_actions=True, confirm_fn=lambda action: False)
        target = tmp_path / "refused.py"

        result = jarvis.write_file(str(target), "should not be written")

        assert not target.exists()
        assert "annule" in result

    def test_write_error_returns_message_without_raising(self, tmp_path, monkeypatch):
        jarvis = make_jarvis(tmp_path)

        def boom(self, content, encoding="utf-8"):
            raise OSError("disk full")

        monkeypatch.setattr(Path, "write_text", boom)

        result = jarvis.write_file(str(tmp_path / "x.py"), "content")

        assert "erreur" in result


class TestRunCommand:
    def test_runs_command_and_returns_output(self, tmp_path):
        jarvis = make_jarvis(tmp_path)

        result = jarvis.run_command("python -c \"print('ok')\"")

        assert "ok" in result
        assert "commande terminee (code 0)" in result

    def test_refused_by_user_does_not_run(self, tmp_path):
        jarvis = make_jarvis(tmp_path, confirm_actions=True, confirm_fn=lambda action: False)

        result = jarvis.run_command("python -c \"print('should not run')\"")

        assert "annule" in result

    def test_timeout_returns_message(self, tmp_path):
        jarvis = make_jarvis(tmp_path)

        result = jarvis.run_command("python -c \"import time; time.sleep(5)\"", timeout=1)

        assert "timeout" in result

    def test_truncates_long_output(self, tmp_path):
        jarvis = make_jarvis(tmp_path)

        result = jarvis.run_command("python -c \"print('x' * 20000)\"", max_chars=100)

        assert "[tronque]" in result
        assert len(result) < 20000

    def test_timeout_actually_bounds_wall_clock_time(self, tmp_path):
        import time

        jarvis = make_jarvis(tmp_path)
        start = time.monotonic()

        jarvis.run_command("python -c \"import time; time.sleep(5)\"", timeout=1)

        elapsed = time.monotonic() - start
        assert elapsed < 3, f"run_command took {elapsed:.2f}s, expected it to return within ~1-2s of the timeout"
