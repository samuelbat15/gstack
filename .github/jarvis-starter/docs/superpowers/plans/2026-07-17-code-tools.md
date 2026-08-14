# Jarvis code-tools (write_file + run_command) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Jarvis's agentic loop two new tools — `write_file` and `run_command` — so it can create files and execute commands, gated by the existing `confirm()` `[o/N]` flow, with a direct-command mirror for each (`ecris <chemin> : <contenu>`, `execute <commande>`).

**Architecture:** Two new plain methods on the `Jarvis` class in `jarvis.py` (`write_file`, `run_command`) — **not** a separate module. The spec (`docs/superpowers/specs/2026-07-16-code-tools-design.md`) assumed a `web_tools.py`-style pure-module pattern, but that module was never actually built; the real, working pattern in this codebase (`search_web`, `open_allowed_target`, `launch_app`) is a plain method on `Jarvis` that calls `self.confirm(...)` inline, then acts, then calls `self.speaker.say(...)`. This plan follows the real pattern, not the spec's incorrect assumption. Same golden rule either way: confirm before acting, return a string, never raise.

**Tech Stack:** Python stdlib only — `subprocess` and `pathlib.Path` are already imported in `jarvis.py`. No new dependencies.

---

## Context for the engineer

`jarvis.py` (`c:/Users/aiell/Projects/gstack/.github/jarvis-starter/jarvis.py`) is a single-file assistant. It has:
- An agentic loop (`run_agentic`) that asks an LLM to emit `tool_calls`, then dispatches each through `execute_agent_tool(self, tool_name, args)` (a big `if/elif` chain, jarvis.py:1145-1213).
- A parallel "direct command" path in `handle(self, text)` (jarvis.py:714-846) for typing e.g. `cherche <query>` or `ouvre <site>` without going through the LLM planner at all.
- Every tool that does something real calls `self.confirm(f"...")` first (jarvis.py:668-685) — this returns `True` immediately if `Config.confirm_actions` is `False` (used in tests), otherwise prompts `input()` (or calls an injectable `confirm_fn` callable, used in tests to simulate refusal).
- Tests construct a `Jarvis` via a `make_jarvis(tmp_path)`-style helper already established in `tests/test_jarvis_agentic.py:22-24`.

You do not need to read the whole file — the exact lines you touch are given in each task below.

---

## Task 1: `Jarvis.write_file()` method

**Files:**
- Modify: `c:/Users/aiell/Projects/gstack/.github/jarvis-starter/jarvis.py` (insert new method after `launch_app`, which ends at line 1264)
- Test: `c:/Users/aiell/Projects/gstack/.github/jarvis-starter/tests/test_jarvis_code_tools.py` (new file)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_jarvis_code_tools.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd c:/Users/aiell/Projects/gstack/.github/jarvis-starter && python -m pytest tests/test_jarvis_code_tools.py -v`
Expected: FAIL with `AttributeError: 'Jarvis' object has no attribute 'write_file'` (4 errors).

- [ ] **Step 3: Implement `write_file`**

In `jarvis.py`, insert this new method immediately after `launch_app` (which currently ends at line 1264 with `subprocess.Popen([command], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)` followed by a blank line 1265):

```python
    def write_file(self, path: str, content: str) -> str:
        if not self.confirm(f"ecrire le fichier {path}"):
            self.speaker.say("Annule.")
            return "annule par l'utilisateur."

        try:
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        except OSError as exc:
            message = f"erreur - {exc}"
            self.speaker.say(f"Erreur: {message}")
            return message

        size = len(content.encode("utf-8"))
        self.speaker.say(f"Fichier {path} ecrit.")
        return f"fichier ecrit : {path} ({size} octets)."
```

`Path` and no new imports are needed — `pathlib.Path` is already imported at the top of `jarvis.py` (line 17).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd c:/Users/aiell/Projects/gstack/.github/jarvis-starter && python -m pytest tests/test_jarvis_code_tools.py::TestWriteFile -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
cd c:/Users/aiell/Projects/gstack
git add .github/jarvis-starter/jarvis.py .github/jarvis-starter/tests/test_jarvis_code_tools.py
git commit -m "feat(jarvis): add write_file method with confirm gate"
```

---

## Task 2: `Jarvis.run_command()` method

**Files:**
- Modify: `c:/Users/aiell/Projects/gstack/.github/jarvis-starter/jarvis.py` (insert new method right after `write_file`, added in Task 1)
- Test: `c:/Users/aiell/Projects/gstack/.github/jarvis-starter/tests/test_jarvis_code_tools.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_jarvis_code_tools.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd c:/Users/aiell/Projects/gstack/.github/jarvis-starter && python -m pytest tests/test_jarvis_code_tools.py::TestRunCommand -v`
Expected: FAIL with `AttributeError: 'Jarvis' object has no attribute 'run_command'` (4 errors).

- [ ] **Step 3: Implement `run_command`**

In `jarvis.py`, insert this new method directly after the `write_file` method added in Task 1:

```python
    def run_command(self, command: str, timeout: int = 30, max_chars: int = 6000) -> str:
        if not self.confirm(f"executer la commande '{command}'"):
            self.speaker.say("Annule.")
            return "annule par l'utilisateur."

        try:
            result = subprocess.run(
                command,
                shell=True,
                timeout=timeout,
                capture_output=True,
                text=True,
            )
        except subprocess.TimeoutExpired:
            message = f"timeout apres {timeout}s."
            self.speaker.say(f"Erreur: {message}")
            return message
        except OSError as exc:
            message = f"erreur - {exc}"
            self.speaker.say(f"Erreur: {message}")
            return message

        output = result.stdout
        if result.stderr:
            output += f"\n[stderr] {result.stderr}"
        output = output.strip()
        if len(output) > max_chars:
            output = output[:max_chars] + " [tronque]"

        self.speaker.say(f"Commande terminee, code {result.returncode}.")
        return f"commande terminee (code {result.returncode}) :\n{output}"
```

`subprocess` is already imported at the top of `jarvis.py` (line 7) — no new import needed.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd c:/Users/aiell/Projects/gstack/.github/jarvis-starter && python -m pytest tests/test_jarvis_code_tools.py::TestRunCommand -v`
Expected: PASS (4 passed). This test suite takes ~1s longer than usual because of the timeout test — that's expected.

- [ ] **Step 5: Commit**

```bash
cd c:/Users/aiell/Projects/gstack
git add .github/jarvis-starter/jarvis.py .github/jarvis-starter/tests/test_jarvis_code_tools.py
git commit -m "feat(jarvis): add run_command method with confirm gate and timeout"
```

---

## Task 3: Wire both tools into the agentic loop (`execute_agent_tool` + `AGENTIC_SYSTEM_INSTRUCTIONS`)

**Files:**
- Modify: `c:/Users/aiell/Projects/gstack/.github/jarvis-starter/jarvis.py:57-61` (tool list in `AGENTIC_SYSTEM_INSTRUCTIONS`)
- Modify: `c:/Users/aiell/Projects/gstack/.github/jarvis-starter/jarvis.py:1211-1213` (`execute_agent_tool` dispatch)
- Test: `c:/Users/aiell/Projects/gstack/.github/jarvis-starter/tests/test_jarvis_code_tools.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_jarvis_code_tools.py`:

```python
class TestExecuteAgentToolIntegration:
    def test_write_file_tool_dispatch(self, tmp_path):
        jarvis = make_jarvis(tmp_path)
        target = tmp_path / "agent_written.py"

        result = jarvis.execute_agent_tool(
            "write_file", {"path": str(target), "content": "x = 42"}
        )

        assert result.startswith("write_file: fichier ecrit")
        assert target.read_text(encoding="utf-8") == "x = 42"

    def test_write_file_missing_path(self, tmp_path):
        jarvis = make_jarvis(tmp_path)

        result = jarvis.execute_agent_tool("write_file", {"content": "x = 1"})

        assert result == "write_file: chemin manquant."

    def test_run_command_tool_dispatch(self, tmp_path):
        jarvis = make_jarvis(tmp_path)

        result = jarvis.execute_agent_tool(
            "run_command", {"command": "python -c \"print('ok')\""}
        )

        assert result.startswith("run_command: commande terminee")
        assert "ok" in result

    def test_run_command_missing_command(self, tmp_path):
        jarvis = make_jarvis(tmp_path)

        result = jarvis.execute_agent_tool("run_command", {})

        assert result == "run_command: commande manquante."
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd c:/Users/aiell/Projects/gstack/.github/jarvis-starter && python -m pytest tests/test_jarvis_code_tools.py::TestExecuteAgentToolIntegration -v`
Expected: FAIL — all 4 return `"write_file: outil non autorise."` / `"run_command: outil non autorise."` (the fallback line at jarvis.py:1213), since `execute_agent_tool` doesn't know these tool names yet.

- [ ] **Step 3: Wire the dispatch and the tool list**

In `jarvis.py`, current lines 57-61 read:

```
- graphity_recall {"query": "question ou sujet"}
- graphity_remember {"text": "fait durable a memoriser"}
- create_reminder {"when": "dans 20 minutes | a 15h00", "text": "texte du rappel"}
- look_around {"question": "ce que tu veux savoir de la scene (optionnel)"}
- check_gmail {"query": "requete de recherche Gmail (optionnel, vide = mails recents)"}
```

Add two lines immediately after `check_gmail` (before the blank line and `Regles:` at line 63):

```
- write_file {"path": "chemin/fichier", "content": "contenu texte du fichier"}
- run_command {"command": "commande shell a executer"}
```

In `jarvis.py`, `execute_agent_tool` currently ends with (lines 1208-1213):

```python
        if tool_name == "check_gmail":
            query = as_text(args.get("query"))
            result = self.search_emails(query) if query else self.describe_recent_emails()
            return "check_gmail: " + result

        return f"{tool_name}: outil non autorise."
```

Insert two new branches between `check_gmail` and the final `return` line:

```python
        if tool_name == "check_gmail":
            query = as_text(args.get("query"))
            result = self.search_emails(query) if query else self.describe_recent_emails()
            return "check_gmail: " + result

        if tool_name == "write_file":
            path = as_text(args.get("path"))
            content = as_text(args.get("content"))
            if not path:
                return "write_file: chemin manquant."
            return "write_file: " + self.write_file(path, content)

        if tool_name == "run_command":
            command = as_text(args.get("command"))
            if not command:
                return "run_command: commande manquante."
            return "run_command: " + self.run_command(command)

        return f"{tool_name}: outil non autorise."
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd c:/Users/aiell/Projects/gstack/.github/jarvis-starter && python -m pytest tests/test_jarvis_code_tools.py -v`
Expected: PASS (12 passed — all tests from Tasks 1-3 combined).

- [ ] **Step 5: Commit**

```bash
cd c:/Users/aiell/Projects/gstack
git add .github/jarvis-starter/jarvis.py .github/jarvis-starter/tests/test_jarvis_code_tools.py
git commit -m "feat(jarvis): wire write_file/run_command into the agentic tool dispatcher"
```

---

## Task 4: Direct commands (`execute <commande>`, `ecris <chemin> : <contenu>`) + help text

**Files:**
- Modify: `c:/Users/aiell/Projects/gstack/.github/jarvis-starter/jarvis.py:204-206` (`looks_like_local_command`)
- Modify: `c:/Users/aiell/Projects/gstack/.github/jarvis-starter/jarvis.py:828-838` (`handle`, insert after the `ouvre`/`lance` branch)
- Modify: `c:/Users/aiell/Projects/gstack/.github/jarvis-starter/jarvis.py:73-109` (`HELP_TEXT`)
- Test: `c:/Users/aiell/Projects/gstack/.github/jarvis-starter/tests/test_jarvis_code_tools.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_jarvis_code_tools.py`:

```python
class TestLooksLikeLocalCommand:
    def test_recognizes_execute_prefix(self):
        assert looks_like_local_command("execute python --version")

    def test_recognizes_ecris_prefix(self):
        assert looks_like_local_command("ecris test.py : print(1)")


class TestHandleDirectCommands:
    def test_execute_prefix_runs_command(self, tmp_path, monkeypatch):
        jarvis = make_jarvis(tmp_path)
        spoken = []
        monkeypatch.setattr(jarvis.speaker, "say", spoken.append)

        continue_running = jarvis.handle("execute python -c \"print('ok')\"")

        assert continue_running is True
        assert any("code 0" in msg for msg in spoken)

    def test_ecris_prefix_writes_file(self, tmp_path, monkeypatch):
        jarvis = make_jarvis(tmp_path)
        target = tmp_path / "note.py"
        monkeypatch.setattr(jarvis.speaker, "say", lambda text: None)

        jarvis.handle(f"ecris {target} : print(1)")

        assert target.read_text(encoding="utf-8") == "print(1)"

    def test_ecris_without_separator_shows_format_hint(self, tmp_path, monkeypatch):
        jarvis = make_jarvis(tmp_path)
        spoken = []
        monkeypatch.setattr(jarvis.speaker, "say", spoken.append)

        jarvis.handle("ecris just-a-path-no-separator")

        assert any("Format attendu" in msg for msg in spoken)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd c:/Users/aiell/Projects/gstack/.github/jarvis-starter && python -m pytest tests/test_jarvis_code_tools.py::TestLooksLikeLocalCommand tests/test_jarvis_code_tools.py::TestHandleDirectCommands -v`
Expected: FAIL — `test_recognizes_execute_prefix` and `test_recognizes_ecris_prefix` fail (prefixes not recognized yet); the `handle()` tests fail because `execute `/`ecris ` fall through to the `agent`/LLM path instead of running the tool directly (with `confirm_actions=False` and no AI configured, they'll hit the `LOCAL_ONLY_MESSAGE` branch instead).

- [ ] **Step 3: Add the prefixes and the direct-command branches**

In `jarvis.py`, `looks_like_local_command` currently has (lines 204-206):

```python
    return command in exact_commands or command.startswith(
        ("note ", "cherche ", "ouvre ", "lance ", "graphity ", "rappelle-moi ", "regarde ", "mail cherche ")
    )
```

Change it to:

```python
    return command in exact_commands or command.startswith(
        ("note ", "cherche ", "ouvre ", "lance ", "graphity ", "rappelle-moi ", "regarde ", "mail cherche ", "execute ", "ecris ")
    )
```

In `jarvis.py`, `handle()` currently has (lines 834-838):

```python
        if command.startswith("ouvre ") or command.startswith("lance "):
            target = cleaned_text.split(" ", 1)[1].strip()
            if target:
                self.open_allowed_target(target)
            return True
```

Insert two new branches immediately after it (still before the `if not self.ai.enabled:` block that currently follows at line 840):

```python
        if command.startswith("ouvre ") or command.startswith("lance "):
            target = cleaned_text.split(" ", 1)[1].strip()
            if target:
                self.open_allowed_target(target)
            return True

        if command.startswith("execute "):
            cmd = cleaned_text.split(" ", 1)[1].strip()
            if cmd:
                self.run_command(cmd)
            return True

        if command.startswith("ecris "):
            remainder = cleaned_text.split(" ", 1)[1].strip()
            if " : " in remainder:
                path, content = remainder.split(" : ", 1)
                self.write_file(path.strip(), content.strip())
            else:
                self.speaker.say("Format attendu: ecris <chemin> : <contenu>")
            return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd c:/Users/aiell/Projects/gstack/.github/jarvis-starter && python -m pytest tests/test_jarvis_code_tools.py -v`
Expected: PASS (17 passed — all tests from Tasks 1-4 combined).

- [ ] **Step 5: Update `HELP_TEXT` and run the full existing suite**

In `jarvis.py`, `HELP_TEXT` currently ends its command list with (line 99, just before the blank line and `Exemples:` at line 101):

```
- mail cherche <requete Gmail>
```

Add two lines right after it, plus a safety note, so the block becomes:

```
- mail cherche <requete Gmail>
- execute <commande shell>
- ecris <chemin> : <contenu>

Attention: execute et ecris n'ont aucune restriction de dossier ni de
commande bloquee -- la confirmation [o/N] est la seule protection, lis
bien ce qui va s'executer avant de repondre "oui".
```

(This changes the blank-line-then-"Exemples:" structure slightly — keep the existing blank line before `Exemples:` immediately after the new warning paragraph.)

Run the full existing suite to confirm nothing else broke:

Run: `cd c:/Users/aiell/Projects/gstack/.github/jarvis-starter && python -m pytest -v`
Expected: All tests pass, including the new `tests/test_jarvis_code_tools.py` (17 tests) and every pre-existing test file untouched by this change.

- [ ] **Step 6: Commit**

```bash
cd c:/Users/aiell/Projects/gstack
git add .github/jarvis-starter/jarvis.py .github/jarvis-starter/tests/test_jarvis_code_tools.py
git commit -m "feat(jarvis): add execute/ecris direct commands and update help text"
```

---

## Self-review notes (already applied above)

- **Spec coverage:** `write_file`/`run_command` (Objectifs), confirm-gate + no sandbox/blocklist (Non-objectifs), direct-command mirror (Integration), error handling never raising + truncation (Gestion d'erreurs), tests including one real non-mocked command (Tests) — all covered across Tasks 1-4. The spec's `code_tools.py` module structure is intentionally **not** followed (see Architecture note above) since that pattern doesn't actually exist in this codebase; every other requirement is preserved.
- **Placeholder scan:** none — every step has complete, real code.
- **Type consistency:** `write_file(path: str, content: str) -> str` and `run_command(command: str, timeout: int = 30, max_chars: int = 6000) -> str` are used identically in every task (method bodies, `execute_agent_tool` branches, `handle()` branches, and all tests).
