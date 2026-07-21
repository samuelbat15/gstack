# Jarvis Starter

Ce dossier contient une vraie base de depart pour un assistant type Jarvis:
voix optionnelle, cerveau IA optionnel, agents agentic, memoire locale, actions
locales limitees par liste blanche, et confirmation avant d'ouvrir un site ou
une application.

Ce n'est pas le Jarvis d'Iron Man complet. La vraie solution se construit par
couches: entree vocale, raisonnement IA, outils autorises, memoire, securite,
puis integrations maison par maison ou poste par poste.

## Lancement rapide

Depuis PowerShell:

```powershell
cd C:\Users\aiell\Projects\gstack\.github\jarvis-starter
python jarvis.py --text
```

Le mode texte fonctionne sans installation. Sans moteur IA, Jarvis reste en
local basique: commandes directes, notes, heure, statut, ouverture d'outils
autorises. Tu peux deja essayer:

```text
aide
heure
statut
note appeler Sam demain matin
mes notes
ouvre youtube
cherche meteo paris
agent note que je dois appeler Sam puis donne moi l'heure
```

Entre les commandes sans guillemets. Quand Jarvis affiche `[o/N]`, reponds
seulement `o` pour confirmer ou `n` pour annuler, puis tape ta prochaine commande.
Si tu tapes une nouvelle commande pendant une confirmation, Jarvis annule
l'action en attente et passe a cette nouvelle commande.

## Mode local agentic avec Ollama

Oui, tu peux l'utiliser en local. Pour que le cerveau IA soit aussi local, il
faut un modele local. Le chemin le plus simple est Ollama.

1. Installe Ollama.
2. Lance ou telecharge un modele, par exemple `llama3.1:8b`.
3. Copie `env.template` vers `.env`.
4. Configure:

```env
JARVIS_PROVIDER=ollama
OLLAMA_MODEL=llama3.1:8b
OLLAMA_BASE_URL=http://localhost:11434
```

Puis lance:

```powershell
python jarvis.py --text
```

Dans ce mode, les demandes libres passent par une boucle agentic:

```text
Demande utilisateur -> agent planificateur -> JSON tool_calls -> outils locaux
-> observations -> reponse finale
```

Les outils agentic actuels sont:

```text
get_time
get_status
add_note
list_notes
search_web
open_site
launch_app
```

Les actions externes restent confirmees par `[o/N]`.

## Activer l'IA

1. Copie `env.template` vers `.env`.
2. Pour le cloud OpenAI, mets ta cle dans `OPENAI_API_KEY`.
3. Lance:

```powershell
python jarvis.py --text
```

Le prototype utilise l'API Responses d'OpenAI via HTTP standard quand
`OPENAI_API_KEY` est presente. Le modele par defaut est configure dans `.env`
avec `OPENAI_MODEL`.

`JARVIS_PROVIDER=auto` choisit OpenAI si une cle est presente, sinon Ollama si
`OLLAMA_MODEL` est configure, sinon le mode local basique.

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

## Activer la voix

La reconnaissance vocale (ecoute) est 100% locale (`faster-whisper`, modele
`base` par defaut) — aucune cle, aucun envoi audio vers un service cloud. Le
mode voix reste optionnel car micros et pilotes Windows varient selon les
machines.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python jarvis.py --voice
```

Dans la fenetre graphique (`python jarvis.py --gui`), un bouton "Parler" fait
la meme chose : enregistre, transcrit localement, envoie automatiquement le
message des que la transcription est prete.

Si l'installation de `PyAudio` echoue, garde le mode texte ou installe une
roue compatible avec ta version de Python. Pour plus de precision au prix de
plus de lenteur, force un modele Whisper plus gros :

```powershell
$env:JARVIS_WHISPER_MODEL = "small"
```

### Voix de synthese (reponses parlees)

Par defaut, Jarvis parle avec `pyttsx3` (voix Windows SAPI — locale mais
robotique). Pour une voix naturelle, configure ElevenLabs dans `.env` :

```env
ELEVENLABS_API_KEY=ta_cle
ELEVENLABS_VOICE_ID=id_de_la_voix_choisie
```

Choisis une voix sur [elevenlabs.io/app/voice-library](https://elevenlabs.io/app/voice-library)
et copie son `voice_id`. Si la cle/voix sont absentes, ou si l'appel
ElevenLabs echoue (reseau, quota), Jarvis bascule automatiquement sur
`pyttsx3` — aucune configuration cassee ne bloque les reponses.

## Ajouter des actions

Modifie `config.json`.

```json
{
  "sites": {
    "youtube": "https://www.youtube.com"
  },
  "apps": {
    "bloc-notes": "notepad.exe"
  }
}
```

Ne mets jamais de commandes destructrices dans cette liste. Un vrai Jarvis doit
avoir moins de pouvoirs par defaut, puis gagner des permissions une par une.

## Memoire long terme (vault Obsidian)

Jarvis peut memoriser des faits durables directement dans ton vault
Obsidian et les rappeler via le vrai graphe de connaissances `graphify`
(pas un index maison).

1. Installe `graphify` si necessaire (`npm install -g graphify`).
2. Dans `.env`, configure `JARVIS_VAULT_PATH` si ton vault n'est pas
   `C:\Users\aiell\Documents\STARBOXE-Notes` (valeur par defaut).
3. Utilise:

```text
graphity memo campagne SEO
agent souviens-toi que je dois relancer la campagne SEO en aout
```

Les notes de Jarvis s'ecrivent dans `<vault>/04_Agents_IA/Jarvis/` et
declenchent une reconstruction du graphe (`graphify update`) a chaque
ecriture.

## Revisions Jarvis (A/B)

Chaque demande agentic est routee entre deux personas : `v1-fast-local`
(reponses courtes, outils seulement si utiles) et `v2-graph-memory`
(privilegie la memoire du vault). Par defaut, toujours la derniere
revision creee.

```text
graphity revisions
graphity traffic
graphity split 1=50 2=50
graphity latest
```

## Lancer les tests

```powershell
pip install -r requirements-dev.txt
python -m pytest
```

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
`python jarvis.py --daemon` dans le dossier Demarrage (`shell:startup`
dans l'Explorateur), ou une tache planifiee declenchee a l'ouverture de
session. Non automatise par ce starter.

## Architecture reelle

Pour aller jusqu'a une solution de production:

1. Wake word local: detection de "Jarvis" hors ligne.
2. STT: transcription locale ou cloud.
3. LLM local ou cloud: raisonnement, planification, contexte personnel.
4. Agents agentic: planificateur, routeur d'outils, observateur, finaliseur.
5. Memoire: notes, preferences, historique utile, avec suppression possible.
6. TTS: voix naturelle.
7. Supervision: confirmations, logs, mode lecture seule, kill switch.

La regle d'or: l'IA propose, le code verifie, l'utilisateur autorise.
