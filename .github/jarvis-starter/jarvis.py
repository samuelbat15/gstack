from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from graphity_runtime import GraphityRuntime, GraphityStateError


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
- graphity revisions
- graphity traffic
- graphity split 1=50 2=50
- graphity latest
- graphity memo <recherche>

Exemples:
- ouvre youtube
- cherche meteo paris
- note appeler Sam demain matin
- agent note que je dois appeler Sam puis donne moi l'heure
- graphity split 1=50 2=50
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
    }
    return command in exact_commands or command.startswith(("note ", "cherche ", "ouvre ", "lance ", "graphity "))


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
            with urllib.request.urlopen(request, timeout=90) as response:
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


def build_ai_client() -> NoAIClient | OpenAIResponsesClient | OllamaClient:
    provider = os.environ.get("JARVIS_PROVIDER", "auto").strip().casefold()
    openai_model = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini").strip() or "gpt-4.1-mini"
    ollama_model = os.environ.get("OLLAMA_MODEL", "").strip()
    ollama_base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").strip()

    if provider == "none":
        return NoAIClient()
    if provider == "openai":
        return OpenAIResponsesClient(openai_model)
    if provider == "ollama":
        return OllamaClient(ollama_model, ollama_base_url)
    if os.environ.get("OPENAI_API_KEY", "").strip():
        return OpenAIResponsesClient(openai_model)
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


class Jarvis:
    def __init__(self, config: Config, voice: bool, data_dir: Path) -> None:
        self.config = config
        self.listener = Listener(voice=voice)
        self.speaker = Speaker(enabled=voice, name=config.assistant_name)
        self.memory = Memory(data_dir)
        self.ai = build_ai_client()
        self.pending_command: str | None = None

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

    def run(self) -> None:
        mode = "voix" if self.listener.voice else "texte"
        self.speaker.say(f"En ligne en mode {mode}. Tape 'aide' pour les commandes.")

        while True:
            try:
                text = self.listener.listen()
            except (EOFError, KeyboardInterrupt):
                print()
                self.speaker.say("Arret.")
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

        observations: list[str] = []
        for _ in range(3):
            prompt = self.build_agent_prompt(user_text, observations)
            raw_answer = self.ai.ask(prompt, instructions=AGENTIC_SYSTEM_INSTRUCTIONS)
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
                observations.append(self.execute_agent_tool(tool_name, args))

            if final:
                observations.append(f"Message provisoire du planificateur: {final}")

        return "J'ai atteint la limite de boucle agentic. Voici les observations:\n" + "\n".join(observations)

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


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Jarvis starter local.")
    parser.add_argument("--voice", action="store_true", help="Active l'entree/sortie vocale si les dependances existent.")
    parser.add_argument("--text", action="store_true", help="Force le mode texte.")
    parser.add_argument("--config", default="config.json", help="Chemin vers config.json.")
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

    voice = bool(args.voice and not args.text)
    app = Jarvis(config=config, voice=voice, data_dir=data_dir)
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
