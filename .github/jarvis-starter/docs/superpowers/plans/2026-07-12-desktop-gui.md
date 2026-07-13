# Fenêtre graphique Jarvis — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Vraie fenêtre graphique Tkinter pour Jarvis (chat classique),
non-bloquante pendant les appels IA lents (70-95s avec Ollama local),
remplace le terminal comme mode par défaut du raccourci bureau.

**Architecture:** `Speaker`/`Jarvis` gagnent des callbacks optionnels
(`sink`, `confirm_fn`) rétrocompatibles. Nouveau `gui.py` isolé consomme
`Jarvis` via son interface publique uniquement, avec un thread par
message + une queue thread-safe pour ne jamais bloquer/toucher Tkinter
depuis un thread secondaire.

**Tech Stack:** Python 3.11, Tkinter (stdlib, aucune dépendance), pytest.

---

## Fichiers concernés

- Modify: `jarvis-starter/jarvis.py` (`Speaker`, `Jarvis.__init__`,
  `Jarvis.confirm`, `parse_args`, `main`)
- Create: `jarvis-starter/gui.py`
- Modify: `jarvis-starter/launch_jarvis.bat`
- Create: `jarvis-starter/tests/test_gui_wiring.py`
- Modify: `jarvis-starter/README.md`

---

### Task 1: `Speaker`/`Jarvis` — callbacks `sink` et `confirm_fn`

**Files:**
- Modify: `jarvis-starter/jarvis.py`
- Test: `jarvis-starter/tests/test_gui_wiring.py`

- [ ] **Step 1: Écrire les tests qui échouent**

`jarvis-starter/tests/test_gui_wiring.py` :

```python
from __future__ import annotations

from pathlib import Path

from jarvis import Config, Jarvis, Speaker


def make_jarvis(tmp_path, **kwargs) -> Jarvis:
    config = Config(assistant_name="Jarvis", confirm_actions=True, sites={}, apps={})
    return Jarvis(config=config, voice=False, data_dir=tmp_path, vault_path=tmp_path / "vault", **kwargs)


class TestSpeakerSink:
    def test_sink_receives_text_instead_of_print(self):
        received = []
        speaker = Speaker(enabled=False, name="Jarvis", sink=received.append)
        speaker.say("bonjour")
        assert received == ["bonjour"]

    def test_no_sink_does_not_raise(self, capsys):
        speaker = Speaker(enabled=False, name="Jarvis")
        speaker.say("bonjour")
        captured = capsys.readouterr()
        assert "bonjour" in captured.out


class TestJarvisOutputSink:
    def test_output_sink_is_wired_to_speaker(self, tmp_path):
        received = []
        jarvis = make_jarvis(tmp_path, output_sink=received.append)
        jarvis.speaker.say("test")
        assert received == ["test"]

    def test_no_output_sink_keeps_print_behavior(self, tmp_path, capsys):
        jarvis = make_jarvis(tmp_path)
        jarvis.speaker.say("test")
        captured = capsys.readouterr()
        assert "test" in captured.out


class TestJarvisConfirmFn:
    def test_confirm_fn_overrides_input(self, tmp_path):
        jarvis = make_jarvis(tmp_path, confirm_fn=lambda action: False)
        assert jarvis.confirm("ouvrir youtube") is False

    def test_confirm_fn_true_bypasses_input(self, tmp_path):
        jarvis = make_jarvis(tmp_path, confirm_fn=lambda action: True)
        assert jarvis.confirm("ouvrir youtube") is True

    def test_no_confirm_fn_uses_input(self, tmp_path, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda prompt: "oui")
        jarvis = make_jarvis(tmp_path)
        assert jarvis.confirm("ouvrir youtube") is True
```

- [ ] **Step 2: Vérifier que les tests échouent**

Run (depuis `jarvis-starter/`) :

```powershell
python -m pytest tests/test_gui_wiring.py -v
```

Expected: FAIL — `TypeError: Speaker.__init__() got an unexpected keyword
argument 'sink'` (et erreurs similaires pour `output_sink`/`confirm_fn`).

- [ ] **Step 3: Modifier `Speaker`**

Dans `jarvis-starter/jarvis.py`, remplacer :

```python
class Speaker:
    def __init__(self, enabled: bool, name: str) -> None:
        self.name = name
        self.engine = None
        if enabled:
            try:
                import pyttsx3  # type: ignore

                self.engine = pyttsx3.init()
            except Exception:
                self.engine = None

    def say(self, text: str) -> None:
        print(f"{self.name}: {text}")
        if self.engine is None:
            return

        try:
            self.engine.say(text)
            self.engine.runAndWait()
        except Exception:
            pass
```

par :

```python
class Speaker:
    def __init__(self, enabled: bool, name: str, sink: "Callable[[str], None] | None" = None) -> None:
        self.name = name
        self.sink = sink
        self.engine = None
        if enabled:
            try:
                import pyttsx3  # type: ignore

                self.engine = pyttsx3.init()
            except Exception:
                self.engine = None

    def say(self, text: str) -> None:
        if self.sink is not None:
            self.sink(text)
        else:
            print(f"{self.name}: {text}")
        if self.engine is None:
            return

        try:
            self.engine.say(text)
            self.engine.runAndWait()
        except Exception:
            pass
```

Vérifier que `Callable` est importé (`from typing import Any` existe
déjà ; ajouter `Callable` à cet import : `from typing import Any, Callable`).

- [ ] **Step 4: Modifier `Jarvis.__init__` et `Jarvis.confirm`**

Remplacer :

```python
class Jarvis:
    def __init__(self, config: Config, voice: bool, data_dir: Path, vault_path: Path) -> None:
        self.config = config
        self.listener = Listener(voice=voice)
        self.speaker = Speaker(enabled=voice, name=config.assistant_name)
        self.memory = Memory(data_dir)
        self.ai = build_ai_client()
        self.graphity = GraphityRuntime(data_dir / "graphity", vault_path)
        self.reminders = ReminderStore(data_dir)
        self.notifier = Notifier()
        self.pending_command: str | None = None
```

par :

```python
class Jarvis:
    def __init__(
        self,
        config: Config,
        voice: bool,
        data_dir: Path,
        vault_path: Path,
        output_sink: "Callable[[str], None] | None" = None,
        confirm_fn: "Callable[[str], bool] | None" = None,
    ) -> None:
        self.config = config
        self.listener = Listener(voice=voice)
        self.speaker = Speaker(enabled=voice, name=config.assistant_name, sink=output_sink)
        self.memory = Memory(data_dir)
        self.ai = build_ai_client()
        self.graphity = GraphityRuntime(data_dir / "graphity", vault_path)
        self.reminders = ReminderStore(data_dir)
        self.notifier = Notifier()
        self.confirm_fn = confirm_fn
        self.pending_command: str | None = None
```

Puis remplacer la méthode `confirm` :

```python
    def confirm(self, action: str) -> bool:
        if not self.config.confirm_actions:
            return True

        answer_text = clean_user_text(input(f"Confirmer: {action} ? [o/N] "))
        answer = normalize(answer_text)
        if answer in {"o", "oui", "y", "yes"}:
            return True
        if answer and looks_like_local_command(answer_text):
            self.speaker.say(
                "J'attendais seulement oui ou non. J'annule l'action en attente "
                "et je passe a ta nouvelle commande."
            )
            self.pending_command = answer_text
        return False
```

par :

```python
    def confirm(self, action: str) -> bool:
        if not self.config.confirm_actions:
            return True

        if self.confirm_fn is not None:
            return self.confirm_fn(action)

        answer_text = clean_user_text(input(f"Confirmer: {action} ? [o/N] "))
        answer = normalize(answer_text)
        if answer in {"o", "oui", "y", "yes"}:
            return True
        if answer and looks_like_local_command(answer_text):
            self.speaker.say(
                "J'attendais seulement oui ou non. J'annule l'action en attente "
                "et je passe a ta nouvelle commande."
            )
            self.pending_command = answer_text
        return False
```

- [ ] **Step 5: Vérifier que tous les tests passent**

Run:

```powershell
python -m pytest tests/test_gui_wiring.py -v
```

Expected: 6 passed.

- [ ] **Step 6: Suite complète (non-régression)**

Run:

```powershell
python -m pytest -v
```

Expected: 46 passed (40 existants + 6 nouveaux).

- [ ] **Step 7: Commit**

```powershell
git add jarvis-starter/jarvis.py jarvis-starter/tests/test_gui_wiring.py
git commit -m "feat: make Speaker and Jarvis.confirm pluggable for non-console output"
```

---

### Task 2: `gui.py` — fenêtre Tkinter

**Files:**
- Create: `jarvis-starter/gui.py`

- [ ] **Step 1: Créer `gui.py`**

```python
from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import scrolledtext

from jarvis import Jarvis


class JarvisGUI:
    def __init__(self, jarvis: Jarvis, response_queue: "queue.Queue[str]") -> None:
        self.jarvis = jarvis
        self.response_queue = response_queue
        self.root = tk.Tk()
        self.root.title("Jarvis")
        self.root.geometry("520x600")
        self.root.configure(bg="#0a0e14")
        self._build_widgets()
        self._poll_queue()

    def _build_widgets(self) -> None:
        self.history = scrolledtext.ScrolledText(
            self.root,
            state="disabled",
            bg="#0a0e14",
            fg="#8fd3ff",
            insertbackground="#8fd3ff",
            font=("Consolas", 10),
            wrap="word",
        )
        self.history.pack(fill="both", expand=True, padx=8, pady=8)

        entry_frame = tk.Frame(self.root, bg="#0a0e14")
        entry_frame.pack(fill="x", padx=8, pady=(0, 8))

        self.entry = tk.Entry(entry_frame, bg="#141a24", fg="#8fd3ff", insertbackground="#8fd3ff")
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", self._on_send)

        tk.Button(entry_frame, text="Envoyer", command=self._on_send).pack(side="left", padx=(4, 0))

    def _append_line(self, text: str) -> None:
        self.history.configure(state="normal")
        self.history.insert("end", text + "\n")
        self.history.configure(state="disabled")
        self.history.see("end")

    def _on_send(self, event: object = None) -> None:
        text = self.entry.get().strip()
        if not text:
            return
        self.entry.delete(0, "end")
        self._append_line(f"Vous: {text}")
        self._append_line("Jarvis reflechit...")
        threading.Thread(target=self._handle_safely, args=(text,), daemon=True).start()

    def _handle_safely(self, text: str) -> None:
        try:
            self.jarvis.handle(text)
        except Exception as exc:  # noqa: BLE001 - surface any error to the UI instead of a silent thread crash
            self.response_queue.put(f"Erreur interne: {exc}")

    def _poll_queue(self) -> None:
        try:
            while True:
                text = self.response_queue.get_nowait()
                self._replace_thinking(text)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _replace_thinking(self, text: str) -> None:
        self.history.configure(state="normal")
        self.history.delete("end-2l", "end-1l")
        self.history.insert("end", f"Jarvis: {text}\n")
        self.history.configure(state="disabled")
        self.history.see("end")

    def run(self) -> None:
        self.root.mainloop()


def deny_in_gui(action: str) -> bool:
    return False
```

- [ ] **Step 2: Vérifier l'import**

Run :

```powershell
python -c "import gui; print('ok')"
```

Expected: `ok` (confirme l'absence d'erreur de syntaxe/import).

- [ ] **Step 3: Commit**

```powershell
git add jarvis-starter/gui.py
git commit -m "feat: add Tkinter chat window for Jarvis"
```

---

### Task 3: Mode `--gui` et bascule du raccourci bureau

**Files:**
- Modify: `jarvis-starter/jarvis.py` (`parse_args`, `main`)
- Modify: `jarvis-starter/launch_jarvis.bat`

- [ ] **Step 1: Ajouter le flag `--gui`**

Dans `parse_args`, ajouter :

```python
    parser.add_argument("--gui", action="store_true", help="Lance la fenetre graphique au lieu du mode texte.")
```

- [ ] **Step 2: Router `main()` vers la GUI**

Remplacer :

```python
    voice = bool(args.voice and not args.text)
    app = Jarvis(config=config, voice=voice, data_dir=data_dir, vault_path=vault_path)

    if args.daemon:
        app.run_daemon()
        return 0

    app.run()
    return 0
```

par :

```python
    voice = bool(args.voice and not args.text)

    if args.gui:
        import queue as queue_module

        from gui import JarvisGUI, deny_in_gui

        response_queue: "queue_module.Queue[str]" = queue_module.Queue()
        app = Jarvis(
            config=config,
            voice=False,
            data_dir=data_dir,
            vault_path=vault_path,
            output_sink=response_queue.put,
            confirm_fn=deny_in_gui,
        )
        JarvisGUI(app, response_queue).run()
        return 0

    app = Jarvis(config=config, voice=voice, data_dir=data_dir, vault_path=vault_path)

    if args.daemon:
        app.run_daemon()
        return 0

    app.run()
    return 0
```

(Import de `gui`/`queue` fait localement dans la branche `--gui` pour ne
pas forcer Tkinter a etre importe dans les modes `--text`/`--voice`/
`--daemon`, qui n'en ont pas besoin.)

- [ ] **Step 3: Vérifier manuellement**

Run :

```powershell
python jarvis.py --gui
```

Expected: une fenêtre "Jarvis" s'ouvre (fond sombre, historique vide,
champ de saisie). Taper "statut" + Entrée affiche "Vous: statut" puis
"Jarvis reflechit..." brièvement remplacé par la vraie réponse (rapide
pour `statut`, ne passe pas par l'IA). Fermer la fenêtre normalement
(bouton X).

- [ ] **Step 4: Basculer le raccourci bureau**

Modifier `jarvis-starter/launch_jarvis.bat` :

```bat
@echo off
cd /d "%~dp0"
python jarvis.py --gui
if errorlevel 1 (
    echo.
    echo Jarvis a rencontre une erreur au demarrage.
    pause
)
```

(Retire le `pause` inconditionnel de fin — une fenêtre graphique qui se
ferme normalement n'a pas besoin de garder la console ouverte ; le pause
ne sert plus qu'en cas d'échec au démarrage, avant même que Tkinter ouvre
une fenêtre.)

- [ ] **Step 5: Re-tester le raccourci bureau**

Run :

```powershell
.\launch_jarvis.bat
```

Expected: la fenêtre graphique Jarvis s'ouvre directement (pas de
console persistante visible derrière si tout s'est bien lancé).

- [ ] **Step 6: Commit**

```powershell
git add jarvis-starter/jarvis.py jarvis-starter/launch_jarvis.bat
git commit -m "feat: add --gui launch mode and switch the desktop shortcut to it"
```

---

### Task 4: Documentation + vérification finale

**Files:**
- Modify: `jarvis-starter/README.md`

- [ ] **Step 1: Documenter le mode GUI**

Ajouter avant `## Activer la voix` dans `jarvis-starter/README.md` :

```markdown
## Interface graphique

L'icône du bureau lance désormais une vraie fenêtre (Tkinter, aucune
installation supplémentaire) au lieu du terminal.

```powershell
python jarvis.py --gui
```

Le mode texte (`--text`) reste disponible en ligne de commande pour du
débogage. Les commandes `ouvre <site>`/`lance <app>` ne sont pas encore
supportées en mode graphique (elles déclinent automatiquement) — utilise
`--text` pour ces actions en attendant une v2 avec de vraies boîtes de
dialogue de confirmation.
```

- [ ] **Step 2: Commit**

```powershell
git add jarvis-starter/README.md
git commit -m "docs: document the Tkinter GUI mode"
```

- [ ] **Step 3: Suite de tests finale**

Run:

```powershell
python -m pytest -v
```

Expected: 46 passed, 0 failed.

- [ ] **Step 4: `git status` propre**

Run:

```powershell
git status --short
```

Expected: aucun fichier non commit.
