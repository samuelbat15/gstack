# Proactivite : rappels programmes + mode daemon

## Contexte

Sur les 7 couches identifiees en debut de session, la proactivite est
restee a 0% : Jarvis ne fait jamais rien sans qu'on lui parle activement
dans une session `python jarvis.py --text` ouverte. Cette spec ajoute le
premier comportement proactif reel : des rappels programmes (heure ou
delai), declenches meme si aucun terminal Jarvis n'est ouvert au moment
du declenchement, via un mode daemon en fond.

## Objectifs

- Commande directe `rappelle-moi <quand> de <texte>` (delai relatif ou
  heure absolue) + outil agentic equivalent `create_reminder`.
- Commande `mes rappels` pour lister les rappels en attente.
- Nouveau mode `python jarvis.py --daemon` : processus en fond qui
  verifie les rappels dus toutes les 30s et notifie (toast Windows +
  voix si `--voice` est aussi passe), independamment de toute session
  interactive.
- Stockage local simple (`data/reminders.json`), pas de nouvelle
  dependance obligatoire (parsing de date en stdlib pur).

## Non-objectifs

- Pas d'auto-demarrage au boot Windows (documente en README comme etape
  manuelle — creer une tache planifiee ou un raccourci dans le dossier
  Demarrage — mais pas automatise par le code).
- Pas de rappels recurrents (quotidien, hebdomadaire) — uniquement
  ponctuels pour ce premier jet.
- Pas d'annulation/modification d'un rappel deja cree (YAGNI, a
  reprendre si le besoin se confirme a l'usage).
- Pas de synchronisation avec un vrai calendrier (Outlook, Google
  Calendar) — hors scope, deja un morceau a part entiere.

## Architecture

Deux nouveaux modules, memes principes d'isolation que
`vault_memory.py`/`graphity_runtime.py` : logique pure et testable,
aucune dependance sur la classe `Jarvis`.

```text
jarvis-starter/reminders.py       -> ReminderStore + parsing de temps stdlib
jarvis-starter/notifications.py   -> Notifier (toast Windows optionnel)

Jarvis.__init__
  -> self.reminders = ReminderStore(data_dir)
  -> self.notifier = Notifier()

Jarvis.handle() / execute_agent_tool()
  -> "rappelle-moi ...", "mes rappels", create_reminder
       -> reminders.parse_reminder_time(when) + reminders.add(text, trigger_at)

python jarvis.py --daemon
  -> Jarvis.run_daemon()
       -> boucle: reminders.due(now) -> notifier.notify(...) + speaker.say(...)
          -> reminders.mark_fired(id) -> sleep(30)
```

## Composants

### `reminders.py`

```python
RELATIVE_RE = re.compile(r"^dans\s+(\d+)\s*(minutes?|heures?)$", re.IGNORECASE)
ABSOLUTE_RE = re.compile(r"^a\s+(\d{1,2})[h:](\d{2})?$", re.IGNORECASE)


def parse_reminder_time(when_text: str, now: datetime) -> datetime | None:
    """Parse 'dans 20 minutes' / 'dans 2 heures' / 'a 15h00' / 'a 15:00'."""
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
    """Coupe 'dans 20 minutes de appeler Sam' en ('dans 20 minutes', 'appeler Sam')."""
    match = re.match(r"^(.*?)\s+de\s+(.+)$", remainder, re.IGNORECASE)
    if not match:
        return None
    return match.group(1).strip(), match.group(2).strip()


class ReminderStore:
    def __init__(self, data_dir: Path) -> None: ...
    def add(self, text: str, trigger_at: datetime) -> dict: ...
    def pending(self) -> list[dict]: ...          # non declenches
    def due(self, now: datetime) -> list[dict]: ... # non declenches + trigger_at <= now
    def mark_fired(self, reminder_id: str) -> None: ...
```

Stockage : `data/reminders.json`, liste de
`{id, text, trigger_at (isoformat), created_at (isoformat), fired (bool)}`.
Ecriture complete du fichier a chaque `add`/`mark_fired` (meme pattern que
`graphity_runtime.write_json`), pas de verrouillage concurrent necessaire
(un seul processus daemon + une session interactive occasionnelle,
usage local mono-utilisateur).

### `notifications.py`

```python
class Notifier:
    def __init__(self) -> None:
        self.toaster = None
        try:
            from windows_toasts import WindowsToaster, Toast  # type: ignore
            self.toaster = WindowsToaster("Jarvis")
            self._toast_cls = Toast
        except Exception:
            self.toaster = None

    def notify(self, title: str, message: str) -> None:
        if self.toaster is None:
            return
        try:
            toast = self._toast_cls()
            toast.text_fields = [title, message]
            self.toaster.show_toast(toast)
        except Exception:
            pass
```

Import optionnel dans un `try/except Exception` large (meme pattern que
`Speaker`/`Listener` pour `pyttsx3`/`speech_recognition`) : si
`windows-toasts` n'est pas installe, `notify()` ne fait rien silencieux —
Jarvis reste utilisable sans cette dependance.

### Integration `jarvis.py`

- `Jarvis.__init__` : ajoute `self.reminders = ReminderStore(data_dir)` et
  `self.notifier = Notifier()`.
- `handle()` : nouvelles branches `rappelle-moi` et
  `mes rappels`/`liste rappels`/`rappels`.
- `execute_agent_tool` : nouvelle branche `create_reminder`.
- `AGENTIC_SYSTEM_INSTRUCTIONS` : documente l'outil
  `create_reminder {"when": "...", "text": "..."}`.
- `parse_args` : ajoute `--daemon` (`action="store_true"`).
- `main()` : si `args.daemon`, appelle `app.run_daemon()` au lieu de
  `app.run()`.
- Nouvelle methode `Jarvis.run_daemon()` : boucle infinie, verifie les
  rappels dus toutes les 30s, notifie (toast + voix si Speaker a un
  moteur actif), marque comme declenches, gere `KeyboardInterrupt`
  proprement (message d'arret, pas de traceback).

## Flux de donnees

```text
Utilisateur: "rappelle-moi dans 20 minutes de appeler Sam"
  -> handle() detecte "rappelle-moi "
  -> split_reminder_command("dans 20 minutes de appeler Sam")
     -> ("dans 20 minutes", "appeler Sam")
  -> parse_reminder_time("dans 20 minutes", now) -> now + 20min
  -> reminders.add("appeler Sam", trigger_at)
  -> "Rappel programme pour 15:20 : appeler Sam"

[20 minutes plus tard, dans un processus 'python jarvis.py --daemon' separe]
  -> run_daemon(): reminders.due(now) -> [{"text": "appeler Sam", ...}]
  -> notifier.notify("Jarvis", "appeler Sam")
  -> speaker.say("appeler Sam")  # parle seulement si --voice actif sur CE processus
  -> reminders.mark_fired(id)
```

## Gestion d'erreurs

- `parse_reminder_time` retourne `None` sur format non reconnu ; l'appelant
  (`handle()` ou `execute_agent_tool`) renvoie un message d'erreur clair
  avec des exemples de syntaxe valides, jamais d'exception.
- `Notifier.notify()` n'echoue jamais visiblement (toast absent = simple
  no-op), la voix et le log console restent le filet de securite.
- Le daemon continue de tourner meme si `notifier.notify()` leve une
  exception interne (capturee), pour ne jamais rater un rappel suivant a
  cause d'un probleme de notification.
- `run_daemon()` capture `KeyboardInterrupt` explicitement pour un arret
  propre (`Ctrl+C`), pas de stack trace affichee a l'utilisateur.

## Tests

`jarvis-starter/tests/test_reminders.py` (pytest, aucun appel systeme
reel) :

- `parse_reminder_time` : "dans 20 minutes", "dans 2 heures", "a 15h00",
  "a 15:00", "a 9h" (minute implicite = 0), heure deja passee aujourd'hui
  -> programmee pour demain, format invalide -> `None`.
- `split_reminder_command` : cas valide, cas sans " de ", cas avec
  plusieurs " de " dans le texte (doit couper au premier).
- `ReminderStore` : `add` puis `pending()` retourne le rappel ; `due()`
  ne retourne que les rappels dont `trigger_at <= now` ; `mark_fired()`
  retire le rappel de `pending()`/`due()` sans le supprimer du fichier
  (utile pour un futur historique).

`jarvis-starter/tests/test_notifications.py` : verifie que `Notifier()`
ne leve jamais d'exception a la construction ni a `notify()` meme sans
`windows-toasts` installe (cas reel de cet environnement de dev).

Ajout a `requirements.txt` (optionnel, meme categorie que
`pyttsx3`/`SpeechRecognition`) :

```text
windows-toasts>=1.0
```

## Hors scope / suite possible

- Auto-demarrage du daemon au boot Windows (Planificateur de taches ou
  dossier Demarrage) — a documenter en README comme etape manuelle,
  potentiellement automatise dans une iteration future.
- Rappels recurrents, annulation, modification.
- Autres declencheurs proactifs (surveillance de fichiers, alertes
  conditionnelles sur le vault ou le web) — cette spec couvre uniquement
  les rappels a heure/delai comme premiere brique de la couche
  proactivite.
