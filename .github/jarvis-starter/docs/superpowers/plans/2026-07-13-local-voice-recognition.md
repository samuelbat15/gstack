# Voix locale (Whisper) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remplacer la reconnaissance vocale cloud (Google) par une
transcription 100% locale (`faster-whisper`), utilisable via `--voice`
en CLI et via un bouton "Parler" dans la fenêtre graphique.

**Architecture:** Nouveau module `voice.py` isolé qui encapsule
`faster-whisper`. `Listener.listen()` (CLI) et un nouveau bouton dans
`gui.py` appellent tous les deux `voice.transcribe()` — un seul moteur,
deux points d'entrée.

**Tech Stack:** Python 3.11, `faster-whisper` (nouvelle dépendance
optionnelle), `speech_recognition`/`pyaudio` (déjà prévus, jamais
installés dans cet environnement), pytest.

---

## Fichiers concernés

- Create: `jarvis-starter/voice.py`
- Modify: `jarvis-starter/jarvis.py` (`Listener.listen`)
- Modify: `jarvis-starter/gui.py` (bouton "Parler")
- Modify: `jarvis-starter/requirements.txt`
- Modify: `jarvis-starter/README.md`
- Create: `jarvis-starter/tests/test_voice.py`

---

### Task 1: `voice.py` — transcription locale

**Files:**
- Create: `jarvis-starter/voice.py`
- Test: `jarvis-starter/tests/test_voice.py`

- [ ] **Step 1: Écrire les tests qui échouent**

`jarvis-starter/tests/test_voice.py` :

```python
from __future__ import annotations

import voice


class FakeSegment:
    def __init__(self, text: str) -> None:
        self.text = text


class TestTranscribe:
    def test_concatenates_segments(self, monkeypatch):
        class FakeModel:
            def transcribe(self, audio, language):
                return [FakeSegment(" Bonjour "), FakeSegment(" Jarvis ")], None

        monkeypatch.setattr("voice._get_model", lambda: FakeModel())
        result = voice.transcribe(b"fake-wav-bytes")
        assert result == "Bonjour Jarvis"

    def test_empty_segments_returns_empty_string(self, monkeypatch):
        class FakeModel:
            def transcribe(self, audio, language):
                return [], None

        monkeypatch.setattr("voice._get_model", lambda: FakeModel())
        result = voice.transcribe(b"fake-wav-bytes")
        assert result == ""

    def test_model_unavailable_returns_error_string(self, monkeypatch):
        def raise_error():
            raise RuntimeError("faster-whisper non installe")

        monkeypatch.setattr("voice._get_model", raise_error)
        result = voice.transcribe(b"fake-wav-bytes")
        assert result.startswith("voice: whisper indisponible")
```

- [ ] **Step 2: Vérifier que les tests échouent**

Run (depuis `jarvis-starter/`) :

```powershell
python -m pytest tests/test_voice.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'voice'`.

- [ ] **Step 3: Implémenter `voice.py`**

```python
from __future__ import annotations

import io
import os

MODEL_SIZE = "base"
_model = None


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel  # type: ignore

        model_size = os.environ.get("JARVIS_WHISPER_MODEL", MODEL_SIZE)
        _model = WhisperModel(model_size, device="cpu", compute_type="int8")
    return _model


def transcribe(wav_bytes: bytes) -> str:
    try:
        model = _get_model()
    except Exception as exc:
        return f"voice: whisper indisponible - {exc}"

    segments, _info = model.transcribe(io.BytesIO(wav_bytes), language="fr")
    return " ".join(segment.text.strip() for segment in segments).strip()
```

- [ ] **Step 4: Vérifier que tous les tests passent**

Run:

```powershell
python -m pytest tests/test_voice.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Ajouter la dépendance optionnelle**

Ajouter à la fin de `jarvis-starter/requirements.txt` :

```text
faster-whisper>=1.0
```

- [ ] **Step 6: Commit**

```powershell
git add jarvis-starter/voice.py jarvis-starter/tests/test_voice.py jarvis-starter/requirements.txt
git commit -m "feat: add local Whisper transcription module"
```

---

### Task 2: Brancher `Listener.listen()` sur la transcription locale

**Files:**
- Modify: `jarvis-starter/jarvis.py:520-539`

- [ ] **Step 1: Remplacer `Listener.listen()`**

Remplacer :

```python
    def listen(self) -> str:
        if not self.voice:
            return input("Vous: ").strip()

        import speech_recognition as sr  # type: ignore

        assert self.recognizer is not None
        assert self.microphone is not None

        print("Vous pouvez parler...")
        with self.microphone as source:
            self.recognizer.adjust_for_ambient_noise(source, duration=0.4)
            audio = self.recognizer.listen(source, timeout=8, phrase_time_limit=12)

        try:
            return self.recognizer.recognize_google(audio, language="fr-FR").strip()
        except sr.UnknownValueError:
            return ""
        except sr.RequestError as exc:
            return f"erreur reconnaissance vocale: {exc}"
```

par :

```python
    def listen(self) -> str:
        if not self.voice:
            return input("Vous: ").strip()

        assert self.recognizer is not None
        assert self.microphone is not None

        print("Vous pouvez parler...")
        with self.microphone as source:
            self.recognizer.adjust_for_ambient_noise(source, duration=0.4)
            audio = self.recognizer.listen(source, timeout=8, phrase_time_limit=12)

        import voice

        return voice.transcribe(audio.get_wav_data()).strip()
```

(Le `import speech_recognition as sr` dans `__init__` reste inchangé —
toujours nécessaire pour la capture micro. Seule la ligne de
reconnaissance change.)

- [ ] **Step 2: Vérifier que la suite complète passe toujours**

Run:

```powershell
python -m pytest -v
```

Expected: 50 passed (47 existants + 3 `test_voice.py`).

- [ ] **Step 3: Commit**

```powershell
git add jarvis-starter/jarvis.py
git commit -m "feat: use local Whisper instead of cloud Google STT in Listener"
```

---

### Task 3: Bouton "Parler" dans la fenêtre graphique

**Files:**
- Modify: `jarvis-starter/gui.py`

- [ ] **Step 1: Réécrire `gui.py`**

Remplacer tout le contenu de `jarvis-starter/gui.py` par :

```python
from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import scrolledtext

from jarvis import Jarvis


class JarvisGUI:
    def __init__(self, jarvis: Jarvis, response_queue: "queue.Queue[object]") -> None:
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
        self.speak_button = tk.Button(entry_frame, text="Parler", command=self._on_speak)
        self.speak_button.pack(side="left", padx=(4, 0))

    def _append_line(self, text: str) -> None:
        self.history.configure(state="normal")
        self.history.insert("end", text + "\n")
        self.history.configure(state="disabled")
        self.history.see("end")

    def _remove_last_line(self) -> None:
        self.history.configure(state="normal")
        self.history.delete("end-2l", "end-1l")
        self.history.configure(state="disabled")
        self.history.see("end")

    def _on_send(self, event: object = None) -> None:
        text = self.entry.get().strip()
        if not text:
            return
        self.entry.delete(0, "end")
        self._send_text(text)

    def _send_text(self, text: str) -> None:
        self._append_line(f"Vous: {text}")
        self._append_line("Jarvis reflechit...")
        threading.Thread(target=self._handle_safely, args=(text,), daemon=True).start()

    def _handle_safely(self, text: str) -> None:
        try:
            self.jarvis.handle(text)
        except Exception as exc:  # noqa: BLE001 - surface any error to the UI instead of a silent thread crash
            self.response_queue.put(f"Erreur interne: {exc}")

    def _on_speak(self) -> None:
        self.speak_button.configure(state="disabled")
        self._append_line("Jarvis ecoute...")
        threading.Thread(target=self._record_and_transcribe, daemon=True).start()

    def _record_and_transcribe(self) -> None:
        try:
            import speech_recognition as sr  # type: ignore

            import voice

            recognizer = sr.Recognizer()
            with sr.Microphone() as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.4)
                audio = recognizer.listen(source, timeout=8, phrase_time_limit=12)
            text = voice.transcribe(audio.get_wav_data()).strip()
        except Exception as exc:  # noqa: BLE001 - surface mic/model errors instead of crashing the thread
            text = f"voice: erreur micro - {exc}"

        self.response_queue.put(("speech_result", text))

    def _poll_queue(self) -> None:
        try:
            while True:
                item = self.response_queue.get_nowait()
                if isinstance(item, tuple) and item[0] == "speech_result":
                    self._handle_speech_result(item[1])
                else:
                    self._replace_thinking(item)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _handle_speech_result(self, text: str) -> None:
        self.speak_button.configure(state="normal")
        self._remove_last_line()
        if not text or text.startswith("voice:"):
            error_message = text or "Je n'ai pas compris."
            self._append_line(f"Jarvis: {error_message}")
            return
        self._send_text(text)

    def _replace_thinking(self, text: str) -> None:
        self._remove_last_line()
        self._append_line(f"Jarvis: {text}")

    def run(self) -> None:
        self.root.mainloop()


def deny_in_gui(action: str) -> bool:
    return False
```

Note : `text or 'Je n''ai pas compris.'` utilise deux apostrophes
consécutives pour échapper l'apostrophe dans la chaîne Python
delimitée par apostrophes — vérifier que l'éditeur ne le corrompt pas ;
alternative plus sûre si besoin : utiliser des guillemets doubles
`"Je n'ai pas compris."`.

- [ ] **Step 2: Vérifier l'import**

Run :

```powershell
python -c "import gui; print('ok')"
```

Expected: `ok`.

- [ ] **Step 3: Vérifier manuellement (sans microphone requis pour ce test)**

Run :

```powershell
python jarvis.py --gui
```

Expected: la fenêtre s'ouvre avec deux boutons "Envoyer" et "Parler".
Taper "statut" + Entrée fonctionne comme avant (non-régression). Cliquer
"Parler" désactive le bouton, affiche "Jarvis ecoute...", puis (sans
microphone configuré ou en cas d'erreur) affiche un message d'erreur et
réactive le bouton — vérifie qu'aucune exception ne remonte à la console
et que la fenêtre reste utilisable après.

- [ ] **Step 4: Commit**

```powershell
git add jarvis-starter/gui.py
git commit -m "feat: add Parler button for local voice input in the GUI"
```

---

### Task 4: Documentation + vérification finale

**Files:**
- Modify: `jarvis-starter/README.md`

- [ ] **Step 1: Documenter la voix locale**

Dans `jarvis-starter/README.md`, remplacer la section `## Activer la
voix` existante par :

```markdown
## Activer la voix

La reconnaissance vocale est 100% locale (`faster-whisper`, modèle
`base` par défaut) — aucune clé, aucun envoi audio vers un service
cloud. Le mode voix reste optionnel car micros et pilotes Windows
varient selon les machines.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python jarvis.py --voice
```

Dans la fenêtre graphique (`python jarvis.py --gui`), un bouton
"Parler" fait la même chose : enregistre, transcrit localement, envoie
automatiquement le message dès que la transcription est prête.

Si l'installation de `PyAudio` échoue, garde le mode texte ou installe
une roue compatible avec ta version de Python. Pour plus de précision
au prix de plus de lenteur, force un modèle Whisper plus gros :

```powershell
$env:JARVIS_WHISPER_MODEL = "small"
```
```

- [ ] **Step 2: Commit**

```powershell
git add jarvis-starter/README.md
git commit -m "docs: document local Whisper voice recognition"
```

- [ ] **Step 3: Suite de tests finale**

Run:

```powershell
python -m pytest -v
```

Expected: 50 passed, 0 failed.

- [ ] **Step 4: `git status` propre**

Run:

```powershell
git status --short
```

Expected: aucun fichier non commit côté `jarvis-starter/` (les fichiers
`.claude/agents/*` laissés en attente lors d'une session précédente ne
sont pas concernés par ce plan — ne pas y toucher).
