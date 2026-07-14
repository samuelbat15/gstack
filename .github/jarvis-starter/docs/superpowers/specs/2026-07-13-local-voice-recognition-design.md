# Voix locale (Whisper) : ecoute sans cloud, bouton micro GUI

## Contexte

Le mode `--voice` existe dans `jarvis.py` depuis le debut du starter, mais
n'a jamais fonctionne dans cet environnement : `speech_recognition`,
`pyaudio` et `pyttsx3` ne sont pas installes (verifie le 2026-07-13). De
plus, la reconnaissance vocale actuelle appelle
`recognizer.recognize_google(audio, language="fr-FR")` — un service cloud
Google, gratuit mais pas local, incoherent avec le choix Ollama 100%
local retenu pour le reste de Jarvis (voir
`env.template`/`docs/superpowers/plans/2026-07-12-...-fix-ollama` et le
commit "fix: default to local Ollama").

L'utilisateur veut que Jarvis "entende" (voix) avant de s'attaquer a la
vision (camera), et veut la voix utilisable a la fois dans la fenetre
graphique (bouton micro) et en CLI (`--voice`).

## Objectifs

- Remplacer la reconnaissance vocale cloud (Google) par une transcription
  100% locale via `faster-whisper` (modele `base` par defaut).
- Bouton "Parler" dans la fenetre graphique Tkinter : capture, transcrit,
  envoie automatiquement le message des que la transcription est prete —
  pas d'etape de relecture manuelle (choix explicite de l'utilisateur).
- `python jarvis.py --voice` (CLI) continue de fonctionner, herite du
  meme moteur de transcription local.
- La synthese vocale (`pyttsx3`, deja locale via SAPI Windows) ne change
  pas.

## Non-objectifs

- Pas de reconnaissance vocale continue / mot de reveil ("Hey Jarvis") —
  hors scope, couvert par le roadmap (point 1, perception).
- Pas de choix de modele Whisper par l'utilisateur en v1 (fixe a `base`,
  ajustable uniquement via variable d'environnement pour les utilisateurs
  avances).
- Pas de streaming de transcription en temps reel (mot par mot) — la
  transcription se fait apres la fin de l'enregistrement, comme le
  comportement actuel de `speech_recognition`.
- Pas de correction manuelle de la transcription avant envoi (choix
  explicite : envoi automatique immediat).

## Architecture

Nouveau module `jarvis-starter/voice.py`, isole (meme principe que
`vault_memory.py`/`reminders.py`) : encapsule `faster-whisper`, ne connait
rien de `Jarvis`/`gui.py`.

```text
jarvis.py: Listener.listen()
  -> capture audio via speech_recognition.Microphone (inchange : gestion
     du bruit ambiant, detection de silence, timeout)
  -> voice.transcribe(audio.get_wav_data()) au lieu de
     recognizer.recognize_google(audio, language="fr-FR")

gui.py: JarvisGUI
  -> nouveau bouton "Parler" a cote de "Envoyer"
  -> _on_speak(): thread separe -> voice.record_and_transcribe()
       -> affiche "Jarvis ecoute..." puis "Transcription..."
       -> texte transcrit non-vide -> memes etapes que _on_send()
          (envoi automatique, pas de relecture)
       -> texte vide/erreur -> message d'erreur affiche, rien n'est envoye
```

## Composants

### `voice.py`

```python
from __future__ import annotations

import io
import wave

MODEL_SIZE = "base"  # ajustable via JARVIS_WHISPER_MODEL si besoin de plus de precision
_model = None  # charge une seule fois, reutilise entre les appels


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel  # type: ignore
        import os

        model_size = os.environ.get("JARVIS_WHISPER_MODEL", MODEL_SIZE)
        _model = WhisperModel(model_size, device="cpu", compute_type="int8")
    return _model


def transcribe(wav_bytes: bytes) -> str:
    """Transcrit un WAV (mono, tel que produit par speech_recognition) en texte francais."""
    try:
        model = _get_model()
    except Exception as exc:
        return f"voice: whisper indisponible - {exc}"

    segments, _info = model.transcribe(io.BytesIO(wav_bytes), language="fr")
    text = " ".join(segment.text.strip() for segment in segments).strip()
    return text
```

`compute_type="int8"` reduit la charge CPU (quantification), important
apres l'experience Ollama ou l'inference CPU s'est averee lente — objectif
ici : transcription en quelques secondes, pas en minutes, sur un
enregistrement de 8-12s.

### `Listener` (modifie, `jarvis.py`)

Remplace uniquement l'appel de reconnaissance, garde toute la logique de
capture (microphone, ambient noise, timeout) :

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

        import voice

        return voice.transcribe(audio.get_wav_data()).strip()
```

### `JarvisGUI` (modifie, `gui.py`)

- Nouveau bouton `tk.Button(entry_frame, text="Parler", command=self._on_speak)`.
- `_on_speak()` : desactive le bouton pendant l'enregistrement (evite les
  clics multiples), affiche `"Jarvis ecoute..."`, lance un thread qui :
  1. Capture l'audio via un `speech_recognition.Recognizer`/`Microphone`
     dedie (meme logique que `Listener`, mais sans dependre d'une session
     `Listener` CLI — instancie localement dans `gui.py` pour rester
     isole de `Jarvis`).
  2. Appelle `voice.transcribe(...)`.
  3. Texte non vide et sans prefixe `voice:`/`erreur` -> pousse dans la
     queue comme un message utilisateur, declenche le meme flux que
     `_on_send` (affiche "Vous: {texte}", "Jarvis reflechit...", lance
     `jarvis.handle(texte)`).
  4. Texte vide ou erreur -> affiche le message d'erreur directement,
     n'appelle jamais `jarvis.handle()` avec une chaine vide.
- Reactive le bouton "Parler" a la fin (succes ou erreur), via la meme
  queue de communication thread-safe que les reponses IA.

## Flux de donnees

```text
Utilisateur clique "Parler"
  -> bouton desactive, "Jarvis ecoute..." affiche
  -> thread: capture 8-12s audio -> voice.transcribe(wav_bytes)
  -> "appelle Sam demain" transcrit
  -> queue: ("user_message", "appelle Sam demain")
  -> thread principal (poll_queue): affiche "Vous: appelle Sam demain",
     "Jarvis reflechit...", lance jarvis.handle(...) dans un nouveau thread
  -> reponse normale (meme chemin que taper au clavier)
```

## Gestion d'erreurs

- `voice.transcribe()` ne leve jamais d'exception : `faster-whisper`
  absent, modele introuvable, ou erreur de decodage -> chaine
  `"voice: ..."` retournee, jamais de crash.
- `Listener.listen()` : si `voice.transcribe` retourne une erreur, elle
  est retournee telle quelle comme "texte entendu" — `Jarvis.handle()` la
  traite comme une commande inconnue (comportement degrade mais sans
  crash, coherent avec le reste du fichier).
- GUI : le bouton "Parler" affiche l'erreur directement dans l'historique
  (`"Jarvis: voice: whisper indisponible - ..."`) au lieu de l'envoyer a
  `jarvis.handle()`, pour eviter de gaspiller un appel IA sur une erreur
  de transcription.
- Microphone absent/permissions refusees : `speech_recognition.Microphone()`
  leve une exception a la construction — capturee dans le thread `_on_speak`
  (meme pattern que `_handle_safely` de `gui.py`), affichee comme erreur
  au lieu de crasher le thread silencieusement.

## Tests

`jarvis-starter/tests/test_voice.py` (pytest, aucun appel micro/modele
reel) :

- `transcribe()` : mocke `voice._get_model` pour retourner un faux modele
  dont `.transcribe()` renvoie des segments predefinis -> verifie la
  concatenation du texte.
- `transcribe()` : `_get_model` leve une exception (simulate `faster-whisper`
  absent) -> verifie que le message d'erreur `"voice: whisper indisponible"`
  est retourne, pas d'exception propagee.
- `transcribe()` : segments vides -> retourne une chaine vide (pas
  d'erreur).

Pas de test automatise pour la capture microphone elle-meme (necessite un
peripherique audio reel) ni pour le bouton GUI (necessite un environnement
graphique) — verification manuelle uniquement (voir plan).

Ajout a `requirements.txt` (dependance optionnelle, meme groupe que
`pyttsx3`/`SpeechRecognition`/`PyAudio`) :

```text
faster-whisper>=1.0
```

## Hors scope / suite possible

- Mot de reveil / ecoute continue en arriere-plan.
- Choix du modele Whisper depuis la GUI (actuellement env var seulement).
- Relecture/correction de la transcription avant envoi (ecarte au
  brainstorming — envoi automatique retenu).
- Streaming de transcription en temps reel.
- Vision (camera/webcam) — prochaine spec separee, roadmap point 2/9.
