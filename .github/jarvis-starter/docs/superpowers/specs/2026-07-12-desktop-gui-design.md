# Fenetre graphique Jarvis (Tkinter)

## Contexte

Jarvis n'existe aujourd'hui qu'en terminal (`--text`, `--voice`,
`--daemon`). Apres avoir livre memoire vault, rappels proactifs, fiabilite
IA (Ollama local qwen2.5:7b) et un lanceur bureau, l'utilisateur a
explicitement demande "une vraie appli", pas une fenetre de commande
noire. Design valide via le compagnon visuel (brainstorming du
2026-07-12) : layout "chat classique" (option A), thematisable plus tard
vers un style HUD sombre (option B ecartee pour ce jet, gardee en
reference visuelle).

## Objectifs

- Nouvelle fenetre graphique Tkinter : historique de conversation +
  champ de saisie, meme experience conceptuelle que le mode `--text`
  mais dans une vraie fenetre.
- Aucune nouvelle dependance : Tkinter est dans la stdlib Python sur
  Windows (installe avec Python lui-meme).
- Ne bloque jamais l'interface pendant qu'Ollama reflechit (70-95s
  mesures empiriquement) : message "Jarvis reflechit..." pendant
  l'attente, fenetre reste utilisable (scroll, redimensionner, fermer).
- Nouveau mode `python jarvis.py --gui`.
- Le raccourci bureau existant (`launch_jarvis.bat` -> icone `Jarvis.lnk`)
  bascule vers ce mode graphique.

## Non-objectifs

- Pas d'entree vocale dans la fenetre graphique (le mode `--voice`
  existant reste CLI-only pour cette v1).
- Pas de dialogue de confirmation synchrone pour `ouvre`/`lance` en mode
  GUI (mecanique cross-thread complexe) — ces commandes declinent
  automatiquement en GUI avec un message clair. Voir Hors scope.
- Pas de theme visuel avance (option B "HUD sombre" du brainstorm) —
  cette v1 reste sobre (fond sombre simple, texte lisible), pas
  d'animation, pas d'effet holographique.
- Pas de redesign du `--text`/`--voice`/`--daemon` existants — coexistent
  tels quels, la GUI est un mode supplementaire.

## Architecture

Nouveau module `jarvis-starter/gui.py`, isole de `jarvis.py` (memes
principes que `vault_memory.py`/`reminders.py`) : ne connait de `Jarvis`
que son interface publique (`handle()`), aucune logique metier dupliquee.

```text
jarvis.py: Speaker gagne un parametre optionnel `sink`
  say(text): si sink fourni -> sink(text) ; sinon -> print(...) (inchange)

jarvis.py: Jarvis.__init__ gagne un parametre optionnel `output_sink`
  transmis directement a Speaker(sink=output_sink)

jarvis.py: Jarvis.confirm() gagne un parametre optionnel `confirm_fn`
  si confirm_fn fourni -> confirm_fn(action) ; sinon -> input() (inchange)

gui.py: JarvisGUI
  __init__(jarvis: Jarvis)
    -> construit la fenetre Tkinter (historique + champ de saisie)
  _on_send(text)
    -> affiche "Vous: {text}", puis "Jarvis reflechit..."
    -> lance jarvis.handle(text) dans un thread separe
  _poll_queue()  # via root.after(100, ...), boucle sur le thread principal
    -> lit la queue alimentee par Speaker.sink, remplace "reflechit..."
       par la vraie reponse

main(): --gui -> construit Jarvis(output_sink=queue.put, confirm_fn=deny_gui)
  -> JarvisGUI(app).run()
```

## Composants

### `Speaker` (modifie, `jarvis.py`)

```python
class Speaker:
    def __init__(self, enabled: bool, name: str, sink: Callable[[str], None] | None = None) -> None:
        self.name = name
        self.sink = sink
        self.engine = None
        if enabled:
            try:
                import pyttsx3
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

### `Jarvis` (modifie, `jarvis.py`)

- `__init__` accepte `output_sink: Callable[[str], None] | None = None` et
  `confirm_fn: Callable[[str], bool] | None = None`, tous deux optionnels
  (retro-compatible avec les appels existants `--text`/`--voice`/`--daemon`
  qui ne passent ni l'un ni l'autre).
- `confirm()` : si `self.confirm_fn` est defini, l'appelle au lieu de
  `input(...)`. En mode GUI, `confirm_fn` sera une fonction qui refuse
  systematiquement et renvoie un message explicatif via le sink (voir
  Gestion d'erreurs).

### `gui.py` — `JarvisGUI`

```python
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
            self.root, state="disabled", bg="#0a0e14", fg="#8fd3ff",
            insertbackground="#8fd3ff", font=("Consolas", 10), wrap="word",
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
        threading.Thread(target=self.jarvis.handle, args=(text,), daemon=True).start()

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
```

`response_queue.put` est passe comme `output_sink` a `Jarvis`, donc tout
ce que `Speaker.say()` produit atterrit dans la queue. `_poll_queue`
tourne sur le thread principal Tkinter (seul thread autorise a toucher
les widgets), le thread de `jarvis.handle()` ne touche jamais l'UI
directement — respecte la contrainte stricte de Tkinter (single-threaded
UI).

### Integration `main()` (`jarvis.py`)

- `parse_args` : ajoute `--gui` (`action="store_true"`).
- `main()` : si `args.gui`, construit `Jarvis` avec
  `output_sink=response_queue.put` et `confirm_fn=deny_in_gui`, puis
  `JarvisGUI(app, response_queue).run()` au lieu de `app.run()`.
- `deny_in_gui(action: str) -> bool` (fonction module-level dans
  `jarvis.py` ou `gui.py`) : retourne toujours `False`, le message
  d'echec de `open_allowed_target`/`search_web` ("Annule.") s'affiche
  normalement via le sink — pas de nouveau code necessaire cote
  `Jarvis`, juste ce petit callable.

### `launch_jarvis.bat` (modifie)

Remplace `python jarvis.py --text` par `python jarvis.py --gui`. Garde
`cd /d "%~dp0"` et le `pause` final (utile si la fenetre GUI crash avant
de s'afficher, pour voir l'erreur).

## Flux de donnees

```text
Utilisateur tape "rappelle moi d'appeler Sam" + Entree
  -> _on_send: affiche "Vous: ..." puis "Jarvis reflechit..."
  -> thread demarre: jarvis.handle("rappelle moi d'appeler Sam")
       -> handle() detecte "rappelle-moi ", cree le rappel
       -> self.speaker.say("Rappel programme pour 15:20 : appeler Sam")
       -> Speaker.say() -> self.sink(text) -> response_queue.put(text)
  -> _poll_queue() (thread principal, toutes les 100ms) recupere le texte
  -> _replace_thinking(): supprime la ligne "Jarvis reflechit...",
     affiche "Jarvis: Rappel programme pour 15:20 : appeler Sam"
```

## Gestion d'erreurs

- Si `jarvis.handle()` leve une exception non geree dans le thread
  d'arriere-plan, elle est capturee au niveau du thread (pas de crash
  silencieux ni de fenetre figee) et un message d'erreur generique est
  pousse dans la queue via un `try/except` autour de l'appel dans
  `_on_send`'s thread target.
- Actions `ouvre`/`lance` en mode GUI : `confirm_fn` renvoie toujours
  `False`, donc le flux existant de `Jarvis` affiche deja "Annule." — pas
  de nouveau message a inventer, le comportement de refus existant est
  reutilise tel quel.
- Si Tkinter n'est pas disponible (rare sur Windows, mais possible sur
  certaines installations Python minimalistes) : `python jarvis.py --gui`
  echoue avec l'erreur `ModuleNotFoundError` standard de Python — pas de
  gestion speciale, message d'erreur Python deja clair pour ce cas rare.

## Tests

`jarvis-starter/tests/test_gui_wiring.py` (pytest) — teste le **cablage**
(Speaker/Jarvis avec sink et confirm_fn), pas la fenetre Tkinter
elle-meme (GUI reelle non testable en CI sans affichage) :

- `Speaker(enabled=False, name="Jarvis", sink=callback).say("x")` appelle
  `callback("x")` au lieu de `print`.
- `Speaker(enabled=False, name="Jarvis").say("x")` (sans sink) ne leve pas
  d'exception (comportement `print` existant preserve).
- `Jarvis(..., output_sink=callback)` : `jarvis.speaker.sink is callback`.
- `Jarvis(..., confirm_fn=lambda action: False)` : `jarvis.confirm("x")`
  retourne `False` sans appeler `input()`.
- `Jarvis(...)` sans `confirm_fn` : comportement `input()` existant
  inchange (teste via monkeypatch de `builtins.input`, comme deja fait
  implicitement dans les tests existants de `test_jarvis_agentic.py` en
  evitant tout chemin qui appelle `confirm()`).

Pas de test automatise pour `gui.py` lui-meme (necessiterait un
environnement graphique) — verification manuelle uniquement (voir plan).

## Hors scope / suite possible

- Dialogue de confirmation reel (Tkinter `messagebox.askyesno`) pour
  `ouvre`/`lance` en mode GUI — necessite une synchronisation cross-thread
  bloquante (queue + `threading.Event`), plus complexe, reporte.
- Entree vocale dans la fenetre graphique.
- Theme visuel avance / animations (option B du brainstorm : HUD avec
  indicateurs d'etat, inspire par la vision "Iron Man" plus large —
  voir `docs/ROADMAP.md` point 14).
- Icone/systray, reduction dans la barre des taches, position memorisee.
