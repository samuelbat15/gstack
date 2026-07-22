from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import tts
from graphity_runtime import GraphityRuntime, GraphityStateError
from notifications import Notifier
from reminders import ReminderStore, parse_reminder_time, split_reminder_command
from vault_memory import DEFAULT_VAULT_PATH


SYSTEM_INSTRUCTIONS = """
Tu es Jarvis, un assistant personnel local.
Tu reponds en francais, avec un style bref, direct et calme.
Tu ne pretends jamais avoir execute une action si elle n'a pas ete faite par les outils locaux.
Tu refuses les demandes dangereuses, illegales, intrusives ou destructrices.
Tu expliques clairement ce que l'utilisateur doit confirmer avant toute action sensible.
""".strip()


AGENTIC_SYSTEM_INSTRUCTIONS = """
Tu es le planificateur agentic de Jarvis.
Tu dois repondre uniquement avec un objet JSON valide, sans markdown.

Schema obligatoire:
{
  "thought": "raisonnement court",
  "tool_calls": [
    {"tool": "nom_outil", "args": {"cle": "valeur"}}
  ],
  "final": "reponse finale courte ou chaine vide si tu attends les observations"
}

Outils autorises:
- get_time {}
- get_status {}
- add_note {"text": "texte"}
- list_notes {}
- search_web {"query": "recherche"}
- open_site {"target": "nom autorise dans config.json"}
- launch_app {"target": "nom autorise dans config.json"}
- graphity_recall {"query": "question ou sujet"}
- graphity_remember {"text": "fait durable a memoriser"}
- create_reminder {"when": "dans 20 minutes | a 15h00", "text": "texte du rappel"}
- look_around {"question": "ce que tu veux savoir de la scene (optionnel)"}
- check_gmail {"query": "requete de recherche Gmail (optionnel, vide = mails recents)"}
- write_file {"path": "chemin/fichier", "content": "contenu texte du fichier"}
- run_command {"command": "commande shell a executer"}

Regles:
- N'invente jamais le resultat d'un outil.
- Utilise seulement les outils de la liste.
- Pour ouvrir un site, lancer une app ou chercher sur le web, appelle l'outil.
- Si aucun outil n'est utile, mets tool_calls a [] et donne final.
- Refuse toute action destructive, intrusive, illegale ou non autorisee.
- Reste concis et en francais.
""".strip()


HELP_TEXT = """
Commandes locales:
- aide
- quitte
- heure
- statut
- ouvre <site ou app autorise>
- cherche <recherche web>
- note <texte a memoriser>
- mes notes
- agent <objectif agentic>
- rappelle-moi <dans N minutes|a HH:MM> de <texte>
- mes rappels
- graphity revisions
- graphity traffic
- graphity split 1=50 2=50
- graphity latest
- graphity memo <recherche>
- regarde <question optionnelle>
- buffer video demarre / buffer video arrete
- buffer audio demarre / buffer audio arrete
- buffer demarre / buffer arrete (les deux en parallele)
- buffer statut
- observe video / observe audio / observe (analyse periodique du buffer)
- arrete observation
- mail / mes mails (emails recents)
- mail cherche <requete Gmail>

Exemples:
- ouvre youtube
- cherche meteo paris
- note appeler Sam demain matin
- agent note que je dois appeler Sam puis donne moi l'heure
- graphity split 1=50 2=50
- regarde qu'est-ce qu'il y a sur mon bureau
- buffer demarre
""".strip()


LOCAL_ONLY_MESSAGE = (
    "Commande non reconnue en mode local basique. Tape aide pour voir les commandes. "
    "Pour activer les agents, configure Ollama en local ou ajoute OPENAI_API_KEY dans .env."
)


@dataclass(frozen=True)
class Config:
    assistant_name: str
    confirm_actions: bool
    sites: dict[str, str]
    apps: dict[str, str]


def load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_config(path: Path) -> Config:
    data: dict[str, Any] = {}
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))

    return Config(
        assistant_name=str(data.get("assistant_name", "Jarvis")),
        confirm_actions=bool(data.get("confirm_actions", True)),
        sites=dict(data.get("sites", {})),
        apps=dict(data.get("apps", {})),
    )


def clean_user_text(text: str) -> str:
    cleaned = text.strip()
    while len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {"'", '"', "`"}:
        cleaned = cleaned[1:-1].strip()
    return cleaned


def normalize(text: str) -> str:
    return " ".join(clean_user_text(text).casefold().strip().split())


def looks_like_local_command(text: str) -> bool:
    command = normalize(text)
    exact_commands = {
        "aide",
        "help",
        "commandes",
        "quitte",
        "stop",
        "exit",
        "arret",
        "arrete",
        "au revoir",
        "heure",
        "quelle heure est-il",
        "quelle heure est il",
        "statut",
        "status",
        "mes notes",
        "liste notes",
        "notes",
        "mes rappels",
        "liste rappels",
        "rappels",
        "regarde",
        "buffer video demarre",
        "buffer video arrete",
        "buffer audio demarre",
        "buffer audio arrete",
        "buffer demarre",
        "buffer arrete",
        "buffer statut",
        "observe video",
        "observe audio",
        "observe",
        "arrete observation",
        "mail",
        "mes mails",
    }
    return command in exact_commands or command.startswith(
        ("note ", "cherche ", "ouvre ", "lance ", "graphity ", "rappelle-moi ", "regarde ", "mail cherche ")
    )


def extract_response_text(payload: dict[str, Any]) -> str:
    direct_text = payload.get("output_text")
    if isinstance(direct_text, str) and direct_text.strip():
        return direct_text.strip()

    parts: list[str] = []
    for item in payload.get("output", []):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if not isinstance(content, dict):
                continue
            if content.get("type") in {"output_text", "text"}:
                text = content.get("text")
                if isinstance(text, str):
                    parts.append(text)

    return "\n".join(parts).strip()


class NoAIClient:
    provider_name = "aucun"

    @property
    def enabled(self) -> bool:
        return False

    def status(self) -> str:
        return "inactive, aucun moteur IA configure"

    def ask(
        self,
        user_text: str,
        memory_context: str = "",
        instructions: str = SYSTEM_INSTRUCTIONS,
    ) -> str:
        return LOCAL_ONLY_MESSAGE


class OpenAIResponsesClient:
    def __init__(self, model: str) -> None:
        self.api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        self.model = model
        self.endpoint = "https://api.openai.com/v1/responses"
        self.provider_name = "openai"

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def status(self) -> str:
        if self.enabled:
            return f"activee via OpenAI ({self.model})"
        return "inactive, OPENAI_API_KEY absent"

    def ask(
        self,
        user_text: str,
        memory_context: str = "",
        instructions: str = SYSTEM_INSTRUCTIONS,
    ) -> str:
        if not self.enabled:
            return (
                "Je suis en mode local pour l'instant. Ajoute OPENAI_API_KEY dans .env "
                "pour activer les reponses IA completes. Tape 'aide' pour mes commandes."
            )

        prompt = user_text
        if memory_context:
            prompt = f"Memoire locale recente:\n{memory_context}\n\nDemande:\n{user_text}"

        body = json.dumps(
            {
                "model": self.model,
                "instructions": instructions,
                "input": prompt,
            }
        ).encode("utf-8")

        request = urllib.request.Request(
            self.endpoint,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            return f"Erreur API OpenAI ({exc.code}). Details: {details[:500]}"
        except urllib.error.URLError as exc:
            return f"Impossible de joindre l'API OpenAI: {exc.reason}"
        except TimeoutError:
            return "L'appel IA a expire. Reessaie dans quelques secondes."

        answer = extract_response_text(payload)
        return answer or "J'ai recu une reponse vide du modele."


class OllamaClient:
    def __init__(self, model: str, base_url: str) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.endpoint = f"{self.base_url}/api/generate"
        self.provider_name = "ollama"

    @property
    def enabled(self) -> bool:
        return bool(self.model)

    def status(self) -> str:
        if self.enabled:
            return f"activee via Ollama local ({self.model})"
        return "inactive, OLLAMA_MODEL absent"

    def ask(
        self,
        user_text: str,
        memory_context: str = "",
        instructions: str = SYSTEM_INSTRUCTIONS,
    ) -> str:
        if not self.enabled:
            return LOCAL_ONLY_MESSAGE

        prompt = user_text
        if memory_context:
            prompt = f"Memoire locale recente:\n{memory_context}\n\nDemande:\n{user_text}"

        body = json.dumps(
            {
                "model": self.model,
                "system": instructions,
                "prompt": prompt,
                "stream": False,
            }
        ).encode("utf-8")

        request = urllib.request.Request(
            self.endpoint,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            return f"Erreur Ollama ({exc.code}). Details: {details[:500]}"
        except urllib.error.URLError as exc:
            return f"Impossible de joindre Ollama local: {exc.reason}"
        except TimeoutError:
            return "L'appel Ollama a expire. Verifie que le modele local est charge."

        answer = payload.get("response")
        if isinstance(answer, str) and answer.strip():
            return answer.strip()
        return "J'ai recu une reponse vide d'Ollama."


class OpenRouterClient:
    def __init__(self, model: str) -> None:
        self.api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        self.model = model
        self.endpoint = "https://openrouter.ai/api/v1/chat/completions"
        self.provider_name = "openrouter"

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def status(self) -> str:
        if self.enabled:
            return f"activee via OpenRouter ({self.model})"
        return "inactive, OPENROUTER_API_KEY absent"

    def ask(
        self,
        user_text: str,
        memory_context: str = "",
        instructions: str = SYSTEM_INSTRUCTIONS,
    ) -> str:
        if not self.enabled:
            return (
                "Je suis en mode local pour l'instant. Ajoute OPENROUTER_API_KEY dans .env "
                "pour activer les reponses IA completes via OpenRouter. Tape 'aide' pour mes commandes."
            )

        prompt = user_text
        if memory_context:
            prompt = f"Memoire locale recente:\n{memory_context}\n\nDemande:\n{user_text}"

        body = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": prompt},
                ],
            }
        ).encode("utf-8")

        request = urllib.request.Request(
            self.endpoint,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            return f"Erreur API OpenRouter ({exc.code}). Details: {details[:500]}"
        except urllib.error.URLError as exc:
            return f"Impossible de joindre l'API OpenRouter: {exc.reason}"
        except TimeoutError:
            return "L'appel OpenRouter a expire. Reessaie dans quelques secondes."

        choices = payload.get("choices", [])
        if choices and isinstance(choices[0], dict):
            message = choices[0].get("message", {})
            content = message.get("content") if isinstance(message, dict) else None
            if isinstance(content, str) and content.strip():
                return content.strip()
        return "J'ai recu une reponse vide du modele."


def build_ai_client() -> NoAIClient | OpenAIResponsesClient | OllamaClient | OpenRouterClient:
    provider = os.environ.get("JARVIS_PROVIDER", "auto").strip().casefold()
    openai_model = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini").strip() or "gpt-4.1-mini"
    ollama_model = os.environ.get("OLLAMA_MODEL", "").strip()
    ollama_base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").strip()
    openrouter_model = (
        os.environ.get("OPENROUTER_MODEL", "").strip() or "meta-llama/llama-3.3-70b-instruct:free"
    )

    if provider == "none":
        return NoAIClient()
    if provider == "openai":
        return OpenAIResponsesClient(openai_model)
    if provider == "ollama":
        return OllamaClient(ollama_model, ollama_base_url)
    if provider == "openrouter":
        return OpenRouterClient(openrouter_model)
    if os.environ.get("OPENAI_API_KEY", "").strip():
        return OpenAIResponsesClient(openai_model)
    if os.environ.get("OPENROUTER_API_KEY", "").strip():
        return OpenRouterClient(openrouter_model)
    if ollama_model:
        return OllamaClient(ollama_model, ollama_base_url)
    return NoAIClient()


def extract_json_object(text: str) -> dict[str, Any] | None:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None

    try:
        payload = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return None

    if isinstance(payload, dict):
        return payload
    return None


def as_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if value is None:
        return ""
    return str(value).strip()


class Speaker:
    def __init__(self, enabled: bool, name: str, sink: Callable[[str], None] | None = None) -> None:
        self.name = name
        self.sink = sink
        self.engine = None
        self.elevenlabs_api_key = ""
        self.elevenlabs_voice_id = ""
        self.elevenlabs_model = tts.DEFAULT_MODEL
        if enabled:
            self.elevenlabs_api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
            self.elevenlabs_voice_id = os.environ.get("ELEVENLABS_VOICE_ID", "").strip()
            self.elevenlabs_model = os.environ.get("ELEVENLABS_MODEL", "").strip() or tts.DEFAULT_MODEL
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

        if self.elevenlabs_api_key and self.elevenlabs_voice_id:
            if tts.speak(text, self.elevenlabs_api_key, self.elevenlabs_voice_id, self.elevenlabs_model):
                return

        if self.engine is None:
            return

        try:
            self.engine.say(text)
            self.engine.runAndWait()
        except Exception:
            pass


class Listener:
    def __init__(self, voice: bool) -> None:
        self.voice = voice
        self.recognizer = None
        self.microphone = None

        if voice:
            try:
                import speech_recognition as sr  # type: ignore

                self.recognizer = sr.Recognizer()
                self.microphone = sr.Microphone()
            except Exception:
                self.voice = False

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


class Memory:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.notes_path = self.data_dir / "notes.md"

    def add_note(self, text: str) -> None:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with self.notes_path.open("a", encoding="utf-8") as file:
            file.write(f"- {timestamp}: {text}\n")

    def recent_notes(self, limit: int = 8) -> str:
        if not self.notes_path.exists():
            return ""

        lines = [line.strip() for line in self.notes_path.read_text(encoding="utf-8").splitlines()]
        lines = [line for line in lines if line]
        return "\n".join(lines[-limit:])


DEFAULT_WATCH_INTERVAL = 45.0  # 30-60s retenu : seule cadence realiste sans
# saturer un CPU deja charge (~6-78s par description vision, ~70-95s/tour LLM)


class BufferWatcher(threading.Thread):
    """Analyse periodiquement le dernier element d'un buffer (video ou audio).

    Ne lit jamais en continu (impossible sur ce CPU) : reveil toutes les
    `interval` secondes, prend le DERNIER element disponible (pas de file
    d'attente qui s'accumule), l'analyse, transmet le resultat si non vide.
    Demarrage/arret toujours explicites, jamais automatique.
    """

    def __init__(self, get_latest, describe, on_result, interval: float = DEFAULT_WATCH_INTERVAL) -> None:
        super().__init__(daemon=True)
        self._get_latest = get_latest
        self._describe = describe
        self._on_result = on_result
        self.interval = interval
        self._stop_event = threading.Event()

    def run(self) -> None:
        while not self._stop_event.wait(self.interval):
            item = self._get_latest()
            if item is None:
                continue
            try:
                result = self._describe(item)
            except Exception as exc:  # noqa: BLE001 - surface analysis errors instead of killing the watcher
                result = f"erreur d'analyse: {exc}"
            if result:
                self._on_result(result)

    def stop(self) -> None:
        self._stop_event.set()
        # join() ne garantit pas l'arret si le thread est en plein appel
        # describe() (jusqu'a ~90s sous contention CPU) - il ne repointe le
        # stop_event qu'apres son retour. Timeout court : couvre le cas
        # courant (thread endormi dans wait()), sans bloquer l'appelant sur
        # le pire cas.
        self.join(timeout=5)

    def is_running(self) -> bool:
        return self.is_alive()


class Jarvis:
    def __init__(
        self,
        config: Config,
        voice: bool,
        data_dir: Path,
        vault_path: Path,
        output_sink: Callable[[str], None] | None = None,
        confirm_fn: Callable[[str], bool] | None = None,
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
        self.vision_buffer = None
        self.audio_buffer = None
        self.vision_watcher = None
        self.audio_watcher = None

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

    def run(self) -> None:
        mode = "voix" if self.listener.voice else "texte"
        self.speaker.say(f"En ligne en mode {mode}. Tape 'aide' pour les commandes.")

        while True:
            try:
                text = self.listener.listen()
            except (EOFError, KeyboardInterrupt):
                print()
                self.speaker.say("Arret.")
                self.shutdown()
                return

            if not text:
                continue

            should_continue = self.handle(text)
            if not should_continue:
                return

            while self.pending_command:
                pending = self.pending_command
                self.pending_command = None
                should_continue = self.handle(pending)
                if not should_continue:
                    return

    def handle(self, text: str) -> bool:
        cleaned_text = clean_user_text(text)
        command = normalize(cleaned_text)

        if command in {"quitte", "stop", "exit", "arret", "arrete", "au revoir"}:
            self.speaker.say("Arret du systeme.")
            self.shutdown()
            return False

        if command in {"aide", "help", "commandes"}:
            self.speaker.say(HELP_TEXT)
            return True

        if command in {"heure", "quelle heure est-il", "quelle heure est il"}:
            self.speaker.say(time.strftime("Il est %H:%M."))
            return True

        if command in {"statut", "status"}:
            self.speaker.say(self.status())
            return True

        if command.startswith("note "):
            note = cleaned_text.split(" ", 1)[1].strip()
            if note:
                self.memory.add_note(note)
                self.speaker.say("Note ajoutee.")
            return True

        if command in {"mes notes", "liste notes", "notes"}:
            notes = self.memory.recent_notes()
            self.speaker.say(notes or "Aucune note pour le moment.")
            return True

        if command.startswith("agent "):
            goal = cleaned_text.split(" ", 1)[1].strip()
            if goal:
                self.speaker.say(self.run_agentic(goal))
            return True

        if command.startswith("graphity "):
            self.speaker.say(self.run_graphity_command(cleaned_text.split(" ", 1)[1].strip()))
            return True

        if command.startswith("rappelle-moi "):
            remainder = cleaned_text.split(" ", 1)[1].strip()
            self.speaker.say(self.create_reminder_from_text(remainder))
            return True

        if command in {"mes rappels", "liste rappels", "rappels"}:
            self.speaker.say(self.describe_pending_reminders())
            return True

        if command == "regarde":
            self.speaker.say(self.look_and_describe(""))
            return True

        if command.startswith("regarde "):
            question = cleaned_text.split(" ", 1)[1].strip()
            self.speaker.say(self.look_and_describe(question))
            return True

        if command == "buffer video demarre":
            self.speaker.say(self.start_vision_buffer())
            return True

        if command == "buffer video arrete":
            self.speaker.say(self.stop_vision_buffer())
            return True

        if command == "buffer audio demarre":
            self.speaker.say(self.start_audio_buffer())
            return True

        if command == "buffer audio arrete":
            self.speaker.say(self.stop_audio_buffer())
            return True

        if command == "buffer demarre":
            self.speaker.say(f"{self.start_vision_buffer()} {self.start_audio_buffer()}")
            return True

        if command == "buffer arrete":
            self.speaker.say(f"{self.stop_vision_buffer()} {self.stop_audio_buffer()}")
            return True

        if command == "buffer statut":
            self.speaker.say(self.describe_buffer_status())
            return True

        if command == "observe video":
            self.speaker.say(self.start_vision_watch())
            return True

        if command == "observe audio":
            self.speaker.say(self.start_audio_watch())
            return True

        if command == "observe":
            self.speaker.say(f"{self.start_vision_watch()} {self.start_audio_watch()}")
            return True

        if command == "arrete observation":
            self.speaker.say(f"{self.stop_vision_watch()} {self.stop_audio_watch()}")
            return True

        if command in {"mail", "mes mails"}:
            self.speaker.say(self.describe_recent_emails())
            return True

        if command.startswith("mail cherche "):
            query = cleaned_text.split(" ", 2)[2].strip()
            self.speaker.say(self.search_emails(query))
            return True

        if command.startswith("cherche "):
            query = cleaned_text.split(" ", 1)[1].strip()
            if query:
                self.search_web(query)
            return True

        if command.startswith("ouvre ") or command.startswith("lance "):
            target = cleaned_text.split(" ", 1)[1].strip()
            if target:
                self.open_allowed_target(target)
            return True

        if not self.ai.enabled:
            self.speaker.say(LOCAL_ONLY_MESSAGE)
            return True

        answer = self.run_agentic(cleaned_text)
        self.speaker.say(answer)
        return True

    def run_agentic(self, user_text: str) -> str:
        if not self.ai.enabled:
            return LOCAL_ONLY_MESSAGE

        def executor(revision: dict[str, Any], graph_context: str) -> str:
            instructions = f"{revision['instructions']}\n\n{AGENTIC_SYSTEM_INSTRUCTIONS}"
            observations: list[str] = []
            seen_calls: set[str] = set()
            if graph_context and "vault_memory:" not in graph_context:
                observations.append(f"Contexte du vault (memoire long terme):\n{graph_context}")

            for _ in range(6):
                prompt = self.build_agent_prompt(user_text, observations)
                raw_answer = self.ai.ask(prompt, instructions=instructions)
                payload = extract_json_object(raw_answer)
                if payload is None:
                    return raw_answer

                tool_calls = payload.get("tool_calls", [])
                final = as_text(payload.get("final"))

                if not isinstance(tool_calls, list) or not tool_calls:
                    return final or "Termine."

                for call in tool_calls[:5]:
                    if not isinstance(call, dict):
                        observations.append("Appel outil ignore: format invalide.")
                        continue
                    tool_name = as_text(call.get("tool"))
                    args = call.get("args", {})
                    if not isinstance(args, dict):
                        args = {}

                    signature = f"{tool_name}:{json.dumps(args, sort_keys=True, ensure_ascii=False)}"
                    if signature in seen_calls:
                        observations.append(
                            f"{tool_name}: deja execute avec ces arguments, resultat inchange. "
                            "N'appelle pas le meme outil avec les memes arguments deux fois."
                        )
                        continue
                    seen_calls.add(signature)
                    observations.append(self.execute_agent_tool(tool_name, args))

                if final:
                    observations.append(f"Message provisoire du planificateur: {final}")

            return self.force_final_synthesis(user_text, observations)

        result = self.graphity.invoke(user_text, executor)
        return result.response

    def force_final_synthesis(self, user_text: str, observations: list[str]) -> str:
        observation_block = "\n".join(observations) if observations else "Aucune observation."
        prompt = (
            f"Demande initiale de l'utilisateur:\n{user_text}\n\n"
            "Observations collectees (limite de tours d'outils atteinte, "
            "plus aucun appel d'outil possible):\n"
            f"{observation_block}\n\n"
            "Donne une reponse finale courte et utile en francais, en te "
            "basant uniquement sur ces observations. Pas de JSON, juste la "
            "reponse en texte brut."
        )
        answer = self.ai.ask(prompt, instructions=SYSTEM_INSTRUCTIONS).strip()
        if answer:
            return answer
        return "Je n'ai pas reussi a conclure. Voici les observations:\n" + observation_block

    def run_graphity_command(self, sub_command: str) -> str:
        normalized = normalize(sub_command)

        if normalized == "revisions":
            revisions = self.graphity.list_revisions()
            lines = [f"{r['number']}. {r['label']} ({r['agent_kind']})" for r in revisions]
            return "\n".join(lines) if lines else "Aucune revision."

        if normalized == "traffic":
            return self.graphity.describe_traffic()

        if normalized == "latest":
            self.graphity.set_always_latest()
            return "Traffic route vers la derniere revision."

        if normalized.startswith("split "):
            targets_text = sub_command.split(" ", 1)[1].strip()
            try:
                targets = self.parse_split_targets(targets_text)
                self.graphity.set_manual_split(targets)
            except GraphityStateError as exc:
                return f"graphity split: {exc}"
            return f"Split applique: {targets_text}"

        if normalized.startswith("memo "):
            query = sub_command.split(" ", 1)[1].strip()
            if not query:
                return "graphity memo: requete manquante."
            return self.graphity.memory.recall(query)

        return "Sous-commande graphity inconnue. Essaie: revisions, traffic, split, latest, memo."

    def parse_split_targets(self, text: str) -> dict[str, int]:
        targets: dict[str, int] = {}
        for chunk in text.split():
            if "=" not in chunk:
                raise GraphityStateError(f"Format invalide: {chunk} (attendu cle=valeur)")
            key, value = chunk.split("=", 1)
            key = key.strip()
            try:
                percent = int(value.strip())
            except ValueError:
                raise GraphityStateError(f"Pourcentage invalide: {value}") from None
            targets[key] = percent
        return targets

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

    def look_and_describe(self, question: str) -> str:
        import vision

        return vision.describe_scene(question)

    def describe_recent_emails(self) -> str:
        import gmail_client

        return gmail_client.describe_recent_emails()

    def search_emails(self, query: str) -> str:
        import gmail_client

        if not query:
            return "mail cherche: requete manquante."
        return gmail_client.describe_email_search(query)

    def start_vision_buffer(self) -> str:
        import vision

        if self.vision_buffer is None:
            self.vision_buffer = vision.VisionBuffer()
        if self.vision_buffer.is_running():
            return "Buffer video deja actif."
        self.vision_buffer.start()
        return "Buffer video demarre (capture toutes les 2s)."

    def stop_vision_buffer(self) -> str:
        if self.vision_buffer is None or not self.vision_buffer.is_running():
            return "Buffer video deja arrete."
        self.vision_buffer.stop()
        return "Buffer video arrete."

    def start_audio_buffer(self) -> str:
        import voice as voice_module

        if self.audio_buffer is None:
            self.audio_buffer = voice_module.AudioBuffer()
        if self.audio_buffer.is_running():
            return "Buffer audio deja actif."
        self.audio_buffer.start()
        return "Buffer audio demarre."

    def stop_audio_buffer(self) -> str:
        if self.audio_buffer is None or not self.audio_buffer.is_running():
            return "Buffer audio deja arrete."
        self.audio_buffer.stop()
        return "Buffer audio arrete."

    def start_vision_watch(self) -> str:
        import vision

        start_message = self.start_vision_buffer()
        if self.vision_watcher is not None and self.vision_watcher.is_running():
            return f"{start_message} Observation video deja active."
        interval = float(os.environ.get("JARVIS_WATCH_INTERVAL", DEFAULT_WATCH_INTERVAL))
        self.vision_watcher = BufferWatcher(
            get_latest=self.vision_buffer.latest_frame,
            describe=vision.describe_image,
            on_result=lambda text: self.speaker.say(f"Jarvis observe: {text}"),
            interval=interval,
        )
        self.vision_watcher.start()
        return f"{start_message} Observation active (analyse toutes les {int(interval)}s)."

    def stop_vision_watch(self) -> str:
        watcher_message = ""
        if self.vision_watcher is not None and self.vision_watcher.is_running():
            self.vision_watcher.stop()
            watcher_message = "Observation video arretee. "
        return watcher_message + self.stop_vision_buffer()

    def start_audio_watch(self) -> str:
        import voice as voice_module

        start_message = self.start_audio_buffer()
        if self.audio_watcher is not None and self.audio_watcher.is_running():
            return f"{start_message} Observation audio deja active."
        interval = float(os.environ.get("JARVIS_WATCH_INTERVAL", DEFAULT_WATCH_INTERVAL))
        self.audio_watcher = BufferWatcher(
            get_latest=self.audio_buffer.latest_chunk,
            describe=voice_module.transcribe,
            on_result=lambda text: self.speaker.say(f"Jarvis entend: {text}"),
            interval=interval,
        )
        self.audio_watcher.start()
        return f"{start_message} Observation active (analyse toutes les {int(interval)}s)."

    def stop_audio_watch(self) -> str:
        watcher_message = ""
        if self.audio_watcher is not None and self.audio_watcher.is_running():
            self.audio_watcher.stop()
            watcher_message = "Observation audio arretee. "
        return watcher_message + self.stop_audio_buffer()

    def describe_buffer_status(self) -> str:
        vision_running = self.vision_buffer is not None and self.vision_buffer.is_running()
        audio_running = self.audio_buffer is not None and self.audio_buffer.is_running()
        vision_watching = self.vision_watcher is not None and self.vision_watcher.is_running()
        audio_watching = self.audio_watcher is not None and self.audio_watcher.is_running()
        vision_count = self.vision_buffer.frame_count() if self.vision_buffer else 0
        audio_count = self.audio_buffer.chunk_count() if self.audio_buffer else 0
        return (
            f"Buffer video: {'actif' if vision_running else 'arrete'} ({vision_count} frames)"
            f"{', observation active' if vision_watching else ''}. "
            f"Buffer audio: {'actif' if audio_running else 'arrete'} ({audio_count} segments)"
            f"{', observation active' if audio_watching else ''}."
        )

    def shutdown(self) -> None:
        if self.vision_watcher is not None:
            self.vision_watcher.stop()
        if self.audio_watcher is not None:
            self.audio_watcher.stop()
        if self.vision_buffer is not None:
            self.vision_buffer.stop()
        if self.audio_buffer is not None:
            self.audio_buffer.stop()

    def describe_pending_reminders(self) -> str:
        pending = self.reminders.pending()
        if not pending:
            return "Aucun rappel en attente."
        lines = [
            f"- {datetime.fromisoformat(r['trigger_at']).strftime('%H:%M')} : {r['text']}"
            for r in pending
        ]
        return "\n".join(lines)

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

    def build_agent_prompt(self, user_text: str, observations: list[str]) -> str:
        notes = self.memory.recent_notes()
        allowed_sites = ", ".join(sorted(self.config.sites.keys())) or "aucun"
        allowed_apps = ", ".join(sorted(self.config.apps.keys())) or "aucune"
        observation_block = "\n".join(observations) if observations else "Aucune observation pour le moment."
        notes_block = notes or "Aucune note."

        return f"""
Demande utilisateur:
{user_text}

Memoire locale:
{notes_block}

Contexte systeme:
{self.status()}

Sites autorises:
{allowed_sites}

Applications autorisees:
{allowed_apps}

Observations deja recues:
{observation_block}
""".strip()

    def execute_agent_tool(self, tool_name: str, args: dict[str, Any]) -> str:
        if tool_name == "get_time":
            return time.strftime("get_time: il est %H:%M.")

        if tool_name == "get_status":
            return "get_status: " + self.status()

        if tool_name == "add_note":
            text = as_text(args.get("text"))
            if not text:
                return "add_note: texte manquant."
            self.memory.add_note(text)
            return "add_note: note ajoutee."

        if tool_name == "list_notes":
            notes = self.memory.recent_notes()
            return "list_notes: " + (notes or "aucune note.")

        if tool_name == "search_web":
            query = as_text(args.get("query"))
            if not query:
                return "search_web: requete manquante."
            return "search_web: " + self.search_web(query)

        if tool_name == "open_site":
            target = as_text(args.get("target"))
            if not target:
                return "open_site: cible manquante."
            return "open_site: " + self.open_allowed_target(target)

        if tool_name == "launch_app":
            target = as_text(args.get("target"))
            if not target:
                return "launch_app: cible manquante."
            return "launch_app: " + self.open_allowed_target(target)

        if tool_name == "graphity_recall":
            query = as_text(args.get("query"))
            if not query:
                return "graphity_recall: requete manquante."
            return "graphity_recall: " + self.graphity.memory.recall(query)

        if tool_name == "graphity_remember":
            text = as_text(args.get("text"))
            if not text:
                return "graphity_remember: texte manquant."
            return "graphity_remember: " + self.graphity.memory.remember(text)

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

        if tool_name == "look_around":
            question = as_text(args.get("question"))
            return "look_around: " + self.look_and_describe(question)

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

    def status(self) -> str:
        ai_status = self.ai.status()
        return (
            f"OS: {platform.system()} {platform.release()}. "
            f"Python: {platform.python_version()}. "
            f"IA: {ai_status}. "
            f"Sites autorises: {len(self.config.sites)}. Apps autorisees: {len(self.config.apps)}."
        )

    def search_web(self, query: str) -> str:
        url = "https://duckduckgo.com/?q=" + urllib.parse.quote_plus(query)
        if not self.confirm(f"ouvrir la recherche web '{query}'"):
            self.speaker.say("Annule.")
            return "annulee par l'utilisateur."

        webbrowser.open(url)
        self.speaker.say("Recherche ouverte.")
        return "recherche ouverte."

    def open_allowed_target(self, raw_target: str) -> str:
        target = normalize(raw_target)

        if target in self.config.sites:
            url = self.config.sites[target]
            if not self.confirm(f"ouvrir le site {target}"):
                self.speaker.say("Annule.")
                return "annule par l'utilisateur."
            webbrowser.open(url)
            self.speaker.say(f"J'ouvre {target}.")
            return f"site {target} ouvert."

        if target in self.config.apps:
            command = self.config.apps[target]
            if not self.confirm(f"lancer l'application {target}"):
                self.speaker.say("Annule.")
                return "annule par l'utilisateur."
            self.launch_app(command)
            self.speaker.say(f"Je lance {target}.")
            return f"application {target} lancee."

        allowed = ", ".join(sorted([*self.config.sites.keys(), *self.config.apps.keys()]))
        self.speaker.say(f"Cible non autorisee. Ajoute-la dans config.json. Autorise: {allowed}")
        return f"cible non autorisee. Autorise: {allowed}"

    def launch_app(self, command: str) -> None:
        if platform.system() == "Windows":
            subprocess.Popen([command], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return

        subprocess.Popen([command], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

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

    def run_command(self, command: str, timeout: int = 30, max_chars: int = 6000) -> str:
        if not self.confirm(f"executer la commande '{command}'"):
            self.speaker.say("Annule.")
            return "annule par l'utilisateur."

        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if platform.system() == "Windows" else 0
        process = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=creationflags,
        )

        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            if platform.system() == "Windows":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                    capture_output=True,
                )
            else:
                process.kill()
            process.communicate()
            message = f"timeout apres {timeout}s."
            self.speaker.say(f"Erreur: {message}")
            return message
        except OSError as exc:
            message = f"erreur - {exc}"
            self.speaker.say(f"Erreur: {message}")
            return message

        output = stdout
        if stderr:
            output += f"\n[stderr] {stderr}"
        output = output.strip()
        if len(output) > max_chars:
            output = output[:max_chars] + " [tronque]"

        self.speaker.say(f"Commande terminee, code {process.returncode}.")
        return f"commande terminee (code {process.returncode}) :\n{output}"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Jarvis starter local.")
    parser.add_argument("--voice", action="store_true", help="Active l'entree/sortie vocale si les dependances existent.")
    parser.add_argument("--text", action="store_true", help="Force le mode texte.")
    parser.add_argument("--config", default="config.json", help="Chemin vers config.json.")
    parser.add_argument("--daemon", action="store_true", help="Mode fond: verifie les rappels sans session interactive.")
    parser.add_argument("--gui", action="store_true", help="Lance la fenetre graphique au lieu du mode texte.")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    base_dir = Path(__file__).resolve().parent
    load_env_file(base_dir / ".env")

    args = parse_args(argv)
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = base_dir / config_path

    config = load_config(config_path)
    data_dir = Path(os.environ.get("JARVIS_DATA_DIR", base_dir / "data"))
    if not data_dir.is_absolute():
        data_dir = base_dir / data_dir

    vault_path = Path(os.environ.get("JARVIS_VAULT_PATH", "").strip() or DEFAULT_VAULT_PATH)

    voice = bool(args.voice and not args.text)

    if args.gui:
        import queue as queue_module

        from gui import JarvisGUI, deny_in_gui

        response_queue: "queue_module.Queue[object]" = queue_module.Queue()
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


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
