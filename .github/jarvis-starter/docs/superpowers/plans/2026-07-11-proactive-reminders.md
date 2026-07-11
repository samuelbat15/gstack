# Rappels proactifs + mode daemon — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Premiere brique de proactivite reelle : rappels a heure/delai
donnes, declenches meme sans session interactive ouverte, via un mode
`python jarvis.py --daemon`.

**Architecture:** Deux nouveaux modules isoles (`reminders.py`,
`notifications.py`), branches dans `handle()`/`execute_agent_tool()`, et
une nouvelle methode `Jarvis.run_daemon()`.

**Tech Stack:** Python 3.11 (stdlib `re`/`datetime`/`json`), pytest,
`windows-toasts` en dependance optionnelle (comme `pyttsx3`).

---

## Fichiers concernes

- Create: `jarvis-starter/reminders.py`
- Create: `jarvis-starter/notifications.py`
- Modify: `jarvis-starter/jarvis.py` (`Jarvis.__init__`, `handle`,
  `execute_agent_tool`, `AGENTIC_SYSTEM_INSTRUCTIONS`, `HELP_TEXT`,
  `parse_args`, `main`, nouvelle methode `run_daemon`)
- Modify: `jarvis-starter/requirements.txt` (ajoute `windows-toasts`)
- Modify: `jarvis-starter/README.md`
- Create: `jarvis-starter/tests/test_reminders.py`
- Create: `jarvis-starter/tests/test_notifications.py`

---

### Task 1: `reminders.py` — parsing de temps + `ReminderStore`

**Files:**
- Create: `jarvis-starter/reminders.py`
- Test: `jarvis-starter/tests/test_reminders.py`

- [ ] **Step 1: Écrire les tests qui échouent**

`jarvis-starter/tests/test_reminders.py` :

```python
from __future__ import annotations

from datetime import datetime

from reminders import ReminderStore, parse_reminder_time, split_reminder_command


class TestParseReminderTime:
    def test_relative_minutes(self):
        now = datetime(2026, 7, 11, 15, 0, 0)
        result = parse_reminder_time("dans 20 minutes", now)
        assert result == datetime(2026, 7, 11, 15, 20, 0)

    def test_relative_hours(self):
        now = datetime(2026, 7, 11, 15, 0, 0)
        result = parse_reminder_time("dans 2 heures", now)
        assert result == datetime(2026, 7, 11, 17, 0, 0)

    def test_absolute_with_minutes(self):
        now = datetime(2026, 7, 11, 15, 0, 0)
        result = parse_reminder_time("a 18h30", now)
        assert result == datetime(2026, 7, 11, 18, 30, 0)

    def test_absolute_colon_syntax(self):
        now = datetime(2026, 7, 11, 15, 0, 0)
        result = parse_reminder_time("a 18:30", now)
        assert result == datetime(2026, 7, 11, 18, 30, 0)

    def test_absolute_hour_only_defaults_to_zero_minutes(self):
        now = datetime(2026, 7, 11, 15, 0, 0)
        result = parse_reminder_time("a 9h", now)
        assert result == datetime(2026, 7, 12, 9, 0, 0)

    def test_absolute_already_past_schedules_tomorrow(self):
        now = datetime(2026, 7, 11, 15, 0, 0)
        result = parse_reminder_time("a 9h00", now)
        assert result == datetime(2026, 7, 12, 9, 0, 0)

    def test_invalid_format_returns_none(self):
        now = datetime(2026, 7, 11, 15, 0, 0)
        assert parse_reminder_time("demain matin", now) is None


class TestSplitReminderCommand:
    def test_valid_split(self):
        result = split_reminder_command("dans 20 minutes de appeler Sam")
        assert result == ("dans 20 minutes", "appeler Sam")

    def test_no_separator_returns_none(self):
        assert split_reminder_command("dans 20 minutes appeler Sam") is None

    def test_splits_on_first_de_only(self):
        result = split_reminder_command("a 18h de parler de la campagne SEO")
        assert result == ("a 18h", "parler de la campagne SEO")


class TestReminderStore:
    def test_add_then_pending(self, tmp_path):
        store = ReminderStore(tmp_path)
        store.add("appeler Sam", datetime(2026, 7, 11, 18, 0, 0))
        pending = store.pending()
        assert len(pending) == 1
        assert pending[0]["text"] == "appeler Sam"
        assert pending[0]["fired"] is False

    def test_due_filters_by_time(self, tmp_path):
        store = ReminderStore(tmp_path)
        store.add("passe", datetime(2026, 7, 11, 10, 0, 0))
        store.add("futur", datetime(2026, 7, 11, 20, 0, 0))
        due = store.due(datetime(2026, 7, 11, 15, 0, 0))
        assert [r["text"] for r in due] == ["passe"]

    def test_mark_fired_removes_from_pending(self, tmp_path):
        store = ReminderStore(tmp_path)
        reminder = store.add("appeler Sam", datetime(2026, 7, 11, 18, 0, 0))
        store.mark_fired(reminder["id"])
        assert store.pending() == []
```

- [ ] **Step 2: Vérifier que les tests échouent**

Run (depuis `jarvis-starter/`) :

```powershell
python -m pytest tests/test_reminders.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'reminders'`.

- [ ] **Step 3: Implémenter `reminders.py`**

```python
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

RELATIVE_RE = re.compile(r"^dans\s+(\d+)\s*(minutes?|heures?)$", re.IGNORECASE)
ABSOLUTE_RE = re.compile(r"^a\s+(\d{1,2})[h:](\d{2})?$", re.IGNORECASE)


def parse_reminder_time(when_text: str, now: datetime) -> datetime | None:
    when_text = when_text.strip()

    match = RELATIVE_RE.match(when_text)
    if match:
        amount = int(match.group(1))
        unit = match.group(2).lower()
        delta = timedelta(hours=amount) if unit.startswith("heure") else timedelta(minutes=amount)
        return now + delta

    match = ABSOLUTE_RE.match(when_text)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        trigger_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if trigger_at <= now:
            trigger_at += timedelta(days=1)
        return trigger_at

    return None


def split_reminder_command(remainder: str) -> tuple[str, str] | None:
    match = re.match(r"^(.*?)\s+de\s+(.+)$", remainder, re.IGNORECASE)
    if not match:
        return None
    return match.group(1).strip(), match.group(2).strip()


class ReminderStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.path = data_dir / "reminders.json"
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def _load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, reminders: list[dict[str, Any]]) -> None:
        self.path.write_text(json.dumps(reminders, indent=2, ensure_ascii=False), encoding="utf-8")

    def add(self, text: str, trigger_at: datetime) -> dict[str, Any]:
        reminders = self._load()
        reminder = {
            "id": str(uuid.uuid4()),
            "text": text,
            "trigger_at": trigger_at.isoformat(),
            "created_at": datetime.now().isoformat(),
            "fired": False,
        }
        reminders.append(reminder)
        self._save(reminders)
        return reminder

    def pending(self) -> list[dict[str, Any]]:
        return [r for r in self._load() if not r.get("fired")]

    def due(self, now: datetime) -> list[dict[str, Any]]:
        return [r for r in self.pending() if datetime.fromisoformat(r["trigger_at"]) <= now]

    def mark_fired(self, reminder_id: str) -> None:
        reminders = self._load()
        for reminder in reminders:
            if reminder["id"] == reminder_id:
                reminder["fired"] = True
        self._save(reminders)
```

- [ ] **Step 4: Vérifier que tous les tests passent**

Run:

```powershell
python -m pytest tests/test_reminders.py -v
```

Expected: 13 passed.

- [ ] **Step 5: Commit**

```powershell
git add jarvis-starter/reminders.py jarvis-starter/tests/test_reminders.py
git commit -m "feat: add reminder time parsing and ReminderStore"
```

---

### Task 2: `notifications.py` — Notifier optionnel

**Files:**
- Create: `jarvis-starter/notifications.py`
- Test: `jarvis-starter/tests/test_notifications.py`
- Modify: `jarvis-starter/requirements.txt`

- [ ] **Step 1: Écrire les tests qui échouent**

`jarvis-starter/tests/test_notifications.py` :

```python
from __future__ import annotations

from notifications import Notifier


def test_notifier_never_raises_on_construction():
    Notifier()


def test_notify_never_raises_without_windows_toasts():
    notifier = Notifier()
    notifier.notify("Jarvis", "test de notification")
```

- [ ] **Step 2: Vérifier que les tests échouent**

Run:

```powershell
python -m pytest tests/test_notifications.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'notifications'`.

- [ ] **Step 3: Implémenter `notifications.py`**

```python
from __future__ import annotations


class Notifier:
    def __init__(self) -> None:
        self.toaster = None
        self._toast_cls = None
        try:
            from windows_toasts import Toast, WindowsToaster  # type: ignore

            self.toaster = WindowsToaster("Jarvis")
            self._toast_cls = Toast
        except Exception:
            self.toaster = None

    def notify(self, title: str, message: str) -> None:
        if self.toaster is None or self._toast_cls is None:
            return
        try:
            toast = self._toast_cls()
            toast.text_fields = [title, message]
            self.toaster.show_toast(toast)
        except Exception:
            pass
```

- [ ] **Step 4: Ajouter la dépendance optionnelle**

Ajouter à la fin de `jarvis-starter/requirements.txt` :

```text
windows-toasts>=1.0
```

- [ ] **Step 5: Vérifier que les tests passent**

Run:

```powershell
python -m pytest tests/test_notifications.py -v
```

Expected: 2 passed (`windows-toasts` n'est pas installe dans cet
environnement — confirme que `Notifier` degrade proprement sans lever
d'exception).

- [ ] **Step 6: Commit**

```powershell
git add jarvis-starter/notifications.py jarvis-starter/tests/test_notifications.py jarvis-starter/requirements.txt
git commit -m "feat: add optional Windows toast Notifier"
```

---

### Task 3: Intégration dans `jarvis.py` — commandes + outil agentic

**Files:**
- Modify: `jarvis-starter/jarvis.py`

- [ ] **Step 1: Importer et instancier**

Ajouter en haut de `jarvis-starter/jarvis.py`, avec les autres imports
locaux :

```python
from notifications import Notifier
from reminders import ReminderStore, parse_reminder_time, split_reminder_command
```

Dans `Jarvis.__init__`, ajouter après `self.graphity = ...` :

```python
        self.reminders = ReminderStore(data_dir)
        self.notifier = Notifier()
```

- [ ] **Step 2: Ajouter les branches dans `handle()`**

Insérer après le bloc `if command.startswith("graphity "):` :

```python
        if command.startswith("rappelle-moi "):
            remainder = cleaned_text.split(" ", 1)[1].strip()
            self.speaker.say(self.create_reminder_from_text(remainder))
            return True

        if command in {"mes rappels", "liste rappels", "rappels"}:
            self.speaker.say(self.describe_pending_reminders())
            return True
```

- [ ] **Step 3: Ajouter les méthodes helper sur `Jarvis`**

Ajouter après `run_graphity_command`/`parse_split_targets` :

```python
    def create_reminder_from_text(self, remainder: str) -> str:
        split = split_reminder_command(remainder)
        if split is None:
            return (
                "Format non reconnu. Essaie: rappelle-moi dans 20 minutes de <texte> "
                "ou rappelle-moi a 15h00 de <texte>."
            )
        when_text, text = split
        trigger_at = parse_reminder_time(when_text, datetime.now())
        if trigger_at is None:
            return f"Heure non reconnue: '{when_text}'. Essaie 'dans 20 minutes' ou 'a 15h00'."
        self.reminders.add(text, trigger_at)
        return f"Rappel programme pour {trigger_at.strftime('%H:%M')} : {text}"

    def describe_pending_reminders(self) -> str:
        pending = self.reminders.pending()
        if not pending:
            return "Aucun rappel en attente."
        lines = [
            f"- {datetime.fromisoformat(r['trigger_at']).strftime('%H:%M')} : {r['text']}"
            for r in pending
        ]
        return "\n".join(lines)
```

- [ ] **Step 4: Ajouter l'import `datetime`**

Verifier en haut du fichier que `from datetime import datetime` est
present (sinon l'ajouter avec les autres imports stdlib).

- [ ] **Step 5: Ajouter la branche `create_reminder` dans `execute_agent_tool`**

Insérer avant `return f"{tool_name}: outil non autorise."` :

```python
        if tool_name == "create_reminder":
            when_text = as_text(args.get("when"))
            text = as_text(args.get("text"))
            if not when_text or not text:
                return "create_reminder: when/text manquant."
            trigger_at = parse_reminder_time(when_text, datetime.now())
            if trigger_at is None:
                return f"create_reminder: heure non reconnue '{when_text}'."
            self.reminders.add(text, trigger_at)
            return f"create_reminder: rappel programme pour {trigger_at.strftime('%H:%M')}."
```

- [ ] **Step 6: Documenter l'outil dans `AGENTIC_SYSTEM_INSTRUCTIONS`**

Ajouter a la liste des outils autorises (apres `graphity_remember`) :

```text
- create_reminder {"when": "dans 20 minutes | a 15h00", "text": "texte du rappel"}
```

- [ ] **Step 7: Documenter les commandes dans `HELP_TEXT`**

Ajouter aux commandes locales (apres `agent <objectif agentic>`) :

```text
- rappelle-moi <dans N minutes|a HH:MM> de <texte>
- mes rappels
```

- [ ] **Step 8: Vérifier manuellement**

Run :

```powershell
printf "rappelle-moi dans 20 minutes de appeler Sam\nmes rappels\nquitte\n" | python jarvis.py --text
```

Expected : `Rappel programme pour <HH:MM> : appeler Sam` puis
`- <HH:MM> : appeler Sam`.

- [ ] **Step 9: Commit**

```powershell
git add jarvis-starter/jarvis.py
git commit -m "feat: wire up rappelle-moi command and create_reminder tool"
```

---

### Task 4: Mode `--daemon`

**Files:**
- Modify: `jarvis-starter/jarvis.py` (`parse_args`, `main`, nouvelle methode `run_daemon`)

- [ ] **Step 1: Ajouter le flag `--daemon`**

Dans `parse_args`, ajouter :

```python
    parser.add_argument("--daemon", action="store_true", help="Mode fond: verifie les rappels sans session interactive.")
```

- [ ] **Step 2: Ajouter `run_daemon` sur `Jarvis`**

Ajouter apres `describe_pending_reminders` :

```python
    def run_daemon(self) -> None:
        self.speaker.say("Jarvis demon actif. Verification des rappels toutes les 30s. Ctrl+C pour arreter.")
        try:
            while True:
                now = datetime.now()
                for reminder in self.reminders.due(now):
                    self.notifier.notify("Jarvis", reminder["text"])
                    self.speaker.say(reminder["text"])
                    self.reminders.mark_fired(reminder["id"])
                time.sleep(30)
        except KeyboardInterrupt:
            print()
            self.speaker.say("Demon arrete.")
```

- [ ] **Step 3: Router `main()` vers le daemon**

Remplacer :

```python
    voice = bool(args.voice and not args.text)
    app = Jarvis(config=config, voice=voice, data_dir=data_dir, vault_path=vault_path)
    app.run()
    return 0
```

par :

```python
    voice = bool(args.voice and not args.text)
    app = Jarvis(config=config, voice=voice, data_dir=data_dir, vault_path=vault_path)

    if args.daemon:
        app.run_daemon()
        return 0

    app.run()
    return 0
```

- [ ] **Step 4: Vérifier manuellement (arrêt rapide via Ctrl+C)**

Run dans un terminal, laisser tourner 2-3 secondes puis `Ctrl+C` :

```powershell
python jarvis.py --daemon
```

Expected: message "Jarvis demon actif...", puis "Demon arrete." apres
`Ctrl+C`, aucune stack trace Python affichee.

- [ ] **Step 5: Vérifier qu'un rappel proche se déclenche**

Run (cree un rappel dans 1 minute, puis lance le daemon et attend) :

```powershell
printf "rappelle-moi dans 1 minute de test daemon\nquitte\n" | python jarvis.py --text
python jarvis.py --daemon
```

Attendre ~60-90s, puis `Ctrl+C`. Expected: le rappel "test daemon"
s'affiche/se dit avant l'arret manuel, une notification toast apparait
si `windows-toasts` est installe (sinon silencieux, comportement attendu
sans la dependance optionnelle).

- [ ] **Step 6: Commit**

```powershell
git add jarvis-starter/jarvis.py
git commit -m "feat: add --daemon mode for background reminder checking"
```

---

### Task 5: Documentation README

**Files:**
- Modify: `jarvis-starter/README.md`

- [ ] **Step 1: Ajouter une section proactivité**

Ajouter avant `## Architecture reelle` :

`````markdown
## Proactivite : rappels programmes

Jarvis peut te rappeler quelque chose plus tard, meme si tu n'as pas de
terminal ouvert.

```text
rappelle-moi dans 20 minutes de appeler Sam
rappelle-moi a 18h30 de partir chercher les enfants
mes rappels
```

Pour que les rappels se declenchent sans session ouverte, lance le mode
daemon dans un terminal separe (le laisser tourner en fond) :

```powershell
python jarvis.py --daemon
```

Optionnel : notification Windows native via `pip install windows-toasts`
(sinon Jarvis affiche/dit le rappel sans toast).

Pour demarrer automatiquement au boot Windows : cree un raccourci vers
`python jarvis.py --daemon` dans le dossier Demarrage
(`shell:startup` dans l'Explorateur), ou une tache planifiee declenchee a
l'ouverture de session. Non automatise par ce starter.
`````

- [ ] **Step 2: Commit**

```powershell
git add jarvis-starter/README.md
git commit -m "docs: document proactive reminders and daemon mode"
```

---

### Task 6: Vérification finale

**Files:** aucun changement de code — validation uniquement.

- [ ] **Step 1: Suite de tests complète**

Run:

```powershell
python -m pytest -v
```

Expected: 40 passed, 0 failed (25 existants + 13 `test_reminders.py` + 2
`test_notifications.py`).

- [ ] **Step 2: `git status` propre**

Run:

```powershell
git status --short
```

Expected: aucun fichier non commit. Si des ajustements ont ete
necessaires pendant la verification, les committer avec un message
decrivant precisement la correction (meme discipline que le plan memoire
vault).
