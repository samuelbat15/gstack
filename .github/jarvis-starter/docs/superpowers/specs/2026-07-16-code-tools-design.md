# Outils code (ecriture de fichiers + execution de commandes) pour la boucle agentic de Jarvis

## Contexte

Jarvis (`jarvis-starter/jarvis.py`) a une boucle agentic (`run_agentic`) qui
appelle un planificateur LLM (OpenAI ou Ollama) capable d'invoquer 9 outils
locaux : `get_time`, `get_status`, `add_note`, `list_notes`, `search_web`,
`open_site`, `launch_app`, `graphity_recall`, `graphity_remember`. La spec
`2026-07-11-agentic-web-tools-design.md` a identifie et explicitement reporte
deux categories d'outils : "fichiers/dossiers, controle systeme/applications".
Cette spec traite cette categorie.

Le manque identifie : Jarvis peut chercher/lire de l'information (web, meteo,
memoire vault) mais ne peut rien creer ni executer. Cette spec ajoute la
capacite de "coder" au sens litteral : ecrire un fichier et lancer une
commande.

Cette spec couvre uniquement la couche "raisonnement agentic" (voir README,
section Architecture reelle, etape 4), sur le meme modele que les outils web.
Le "cerveau central / orchestrateur" (point 1 du `docs/ROADMAP.md`) et les
"agents specialises" (point 7) restent hors scope — conformement a la
discipline du roadmap ("ne pas attaquer plusieurs pieces simultanement"),
cette spec ne livre qu'UNE piece : deux outils bas niveau, pas un agent
developpeur complet.

## Objectifs

- Ajouter un outil `write_file` : ecrit du contenu texte dans un fichier
  (cree les dossiers parents si besoin).
- Ajouter un outil `run_command` : execute une commande shell et retourne
  sa sortie.
- Garder la coherence avec le pattern existant (`web_tools.py`) : module pur
  sans effet de bord de confirmation, chaque outil agentic a une commande
  directe equivalente, confirmation `[o/N]` systematique avant execution
  (regle d'or du README : "l'IA propose, le code verifie, l'utilisateur
  autorise").
- Zero nouvelle cle API / secret a gerer.

## Non-objectifs

- **Pas de restriction de chemin/dossier** : contrairement a une sandbox
  dediee, `write_file` et `run_command` peuvent toucher n'importe quel
  chemin du disque — decision explicite de l'utilisateur, la confirmation
  `[o/N]` est le seul garde-fou (coherent avec le reste du projet).
- **Pas de liste noire de commandes en dur** : aucune commande n'est
  bloquee independamment de la confirmation utilisateur — decision
  explicite (le CLAUDE.md global de l'utilisateur a une liste noire pour
  les actions de *Claude Code*, mais ce projet suit sa propre regle deja
  etablie : la confirmation humaine est le garde-fou, pas une liste figee).
- Pas de cache de resultats de commande.
- Pas d'outils specialises par langage (`run_python`, `run_node`, etc.) —
  un seul outil generique `run_command` via le shell, coherent avec la
  philosophie d'outils minimalistes deja en place.
- Pas de changement a la limite de 3 tours de la boucle agentic existante.
- Pas d'orchestrateur central ni d'agent "Developpeur" dedie (roadmap
  points 1 et 7) — hors scope de cette piece.

## Architecture

Nouveau module `jarvis-starter/code_tools.py`, sur le meme modele que
`web_tools.py` : logique pure, testable sans dependre de la classe `Jarvis`
ni d'un vrai `input()`.

```text
Jarvis.handle() / Jarvis.execute_agent_tool()
        |
        v
  code_tools.write_file_text(path, content)          -> str (succes ou erreur)
  code_tools.run_command_text(command, timeout=30)    -> str (sortie ou erreur)
        |
        v
  pathlib.Path.write_text() / subprocess.run(shell=True)
```

Le flux de confirmation reste dans `Jarvis` (pas dans `code_tools.py`), pour
que le module reste une fonction pure sans effet de bord d'input().

## Composants

### `code_tools.write_file_text(path: str, content: str) -> str`

1. Convertit `path` en `pathlib.Path`, resout en chemin absolu.
2. Cree les dossiers parents si besoin (`Path.mkdir(parents=True, exist_ok=True)`).
3. Ecrit `content` via `Path.write_text(content, encoding="utf-8")`.
4. Retourne `"fichier ecrit : <path> (<N> octets)"` en cas de succes.
5. En cas d'erreur (`OSError` : permission refusee, chemin invalide, disque
   plein), retourne `"write_file: erreur - ..."` au lieu de lever une
   exception (coherent avec le pattern de `web_tools.py`).

### `code_tools.run_command_text(command: str, timeout: int = 30, max_chars: int = 6000) -> str`

1. Execute `command` via `subprocess.run(command, shell=True, timeout=timeout, capture_output=True, text=True)`.
2. Combine `stdout` et `stderr` (prefixe `stderr` par `"[stderr] "` si present).
3. Tronque le resultat combine a `max_chars`, ajoute un marqueur `"[tronque]"`
   si troncature.
4. Retourne `"commande terminee (code <returncode>) :\n<sortie>"`.
5. En cas de `subprocess.TimeoutExpired`, retourne
   `"run_command: timeout apres <timeout>s"`.
6. En cas d'autre exception (ex. commande introuvable sur certains shells),
   retourne `"run_command: erreur - ..."`.

### Integration dans `jarvis.py`

- `AGENTIC_SYSTEM_INSTRUCTIONS` : ajoute les entrees
  `write_file {"path": "...", "content": "..."}` et
  `run_command {"command": "..."}` a la liste des outils autorises.
- `execute_agent_tool` : ajoute les branches `write_file` et `run_command`,
  chacune passant par `self.confirm(...)` avant l'appel, exactement comme
  `fetch_url`/`get_weather` le font deja.
- `handle` : ajoute les prefixes de commande directe :
  - `execute <commande>` -> `run_command_text(commande)`
  - `ecris <chemin> : <contenu>` -> `write_file_text(chemin, contenu)`
    (separateur `" : "` ; limite en pratique a du contenu court sur une
    ligne — le mode agentic est la voie normale pour ecrire un vrai fichier
    de code multi-lignes, cette commande directe est un raccourci pour de
    petits fichiers/notes rapides)
- `HELP_TEXT` : documente les deux nouvelles commandes et les deux nouveaux
  outils agentic, avec un avertissement explicite sur l'absence de sandbox
  et de liste noire (rappel visible a chaque `aide`).
- `looks_like_local_command` : ajoute `execute` et `ecris` aux prefixes
  reconnus.

## Flux de donnees

```
Utilisateur: "execute python --version"
  -> Jarvis.handle() detecte prefixe "execute "
  -> confirm("executer la commande: python --version") -> [o/N]
  -> code_tools.run_command_text("python --version") -> sortie
  -> reponse finale parlee/affichee

Utilisateur (mode agentic): "cree un script hello.py qui affiche hello world puis lance-le"
  -> planificateur LLM emet tool_calls: [write_file, run_command]
  -> chaque appel passe par confirm() individuellement, l'utilisateur voit
     le contenu exact du fichier / la commande exacte avant de confirmer
  -> observations accumulees -> tour suivant du planificateur -> reponse finale
```

## Gestion d'erreurs

- Toute fonction de `code_tools.py` retourne toujours une `str` (jamais
  d'exception qui remonte a l'appelant), coherent avec `web_tools.py` et le
  reste de `execute_agent_tool`.
- Si l'utilisateur refuse la confirmation, comportement identique aux autres
  outils : `"annule par l'utilisateur."`.
- Sortie de commande plafonnee a 6000 caracteres retournes, timeout par
  defaut 30s (configurable par appel), pour eviter qu'une commande longue ou
  bloquante ne sature le contexte du prochain appel LLM ou ne bloque la
  boucle indefiniment.
- Le prompt de confirmation affiche le contenu **exact** qui sera ecrit ou
  la commande **exacte** qui sera executee (pas un resume) — c'est le seul
  garde-fou de cette version, il doit donner a l'utilisateur une information
  complete avant de decider.

## Tests

Nouveau fichier `jarvis-starter/tests/test_code_tools.py`, pytest.

Cas couverts :

- `write_file_text` : ecriture reussie dans un dossier temporaire (fixture
  `tmp_path` de pytest, ecriture reelle sur disque, pas de mock), creation
  automatique de dossiers parents inexistants, erreur de permission
  (chemin non-inscriptible, simule via un mock `Path.write_text` levant
  `OSError` pour ce cas precis).
- `run_command_text` : succes (`subprocess.run` mocke, stdout capture),
  echec avec code retour non-zero (stderr capture et prefixe), timeout
  (`subprocess.TimeoutExpired` mocke), troncature de sortie longue
  au-dela de `max_chars`.
- Un test d'integration reel non destructif :
  `run_command_text("python -c \"print('ok')\"")` retourne bien `"ok"`
  dans la sortie (verifie l'assemblage reel de `subprocess.run`, sans
  mock, sans effet de bord).

Nouveau README : section "Commandes" mise a jour avec `execute` et `ecris`,
et un avertissement explicite juste au-dessus : ces deux outils n'ont
**aucune** restriction de chemin ni liste noire de commandes — la
confirmation `[o/N]` est la seule protection, a lire attentivement avant de
repondre `o`.

## Hors scope / suite possible

- Sandbox/dossier de travail dedie (si l'usage reel montre que le "partout
  sur le disque" est trop risque en pratique).
- Liste noire de commandes destructrices (si un incident reel le justifie).
- Outils specialises par langage/runtime.
- Recall automatique du contexte Graphify avant d'ecrire du code (le
  planificateur peut deja appeler `graphity_recall` lui-meme dans un tour
  precedent — pas de couplage automatique ajoute ici).
- Agent "Developpeur" dedie avec son propre contexte (roadmap point 7).
- Orchestrateur central multi-projets (roadmap point 1).
