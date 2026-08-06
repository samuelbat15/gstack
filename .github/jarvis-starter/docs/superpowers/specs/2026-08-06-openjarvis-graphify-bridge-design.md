# Pont Graphify pour OpenJarvis (premier sous-projet de migration)

## Contexte

Objectif a long terme identifie : remplacer le moteur LLM local de
`jarvis-starter` (aujourd'hui Ollama pilote a la main depuis `jarvis.py`) par
le framework local-first **OpenJarvis** (Stanford, `github.com/open-jarvis/
OpenJarvis`, clone en `C:/Users/aiell/Projects/OpenJarvis`).

Analyse du code source d'OpenJarvis : la quasi-totalite des outils deja
construits a la main dans `jarvis-starter` existent deja nativement et de
facon plus mature cote OpenJarvis --  `file_write`/`shell_exec` (avec
`allowed_dirs` optionnel), `web_search`, `text_to_speech`, `audio_tool`, un
systeme d'approbation a paliers (`approval_store.py`, tiers trivial/low/
medium/high) bien au-dela du simple `[o/N]` de `jarvis.py`, et une application
desktop Tauri deja construite (`desktop/src-tauri`). Migrer ces morceaux est
donc une question de **configuration**, pas de portage de code -- hors scope
de cette spec.

**Le seul vrai manque** : `memory_manage.py` d'OpenJarvis ne gere qu'un
fichier `MEMORY.md` plat. Rien de comparable au graphe Graphify construit sur
le vault Obsidian (`C:/Users/aiell/Documents/STARBOXE-Notes/.graphify/` --
51008 noeuds, 112539 aretes, rapport du 2026-07-11). C'est la seule piece
qui necessite du vrai developpement pour que la bascule vers OpenJarvis ne
perde pas de capacite. Cette spec couvre uniquement ce pont.

Le reste du plan de migration (config des outils/engines/channels existants,
GUI Tauri en remplacement du Tkinter, etc.) est hors scope ici et sera
traite comme des sous-projets separes, une fois celui-ci livre.

## Objectifs

- Exposer `graphity_recall(query)` et `graphity_remember(text)` (les deux
  outils agentic deja utilises par `jarvis-starter`) a OpenJarvis, sans
  reecrire la logique du graphe.
- Reutiliser tel quel le moteur existant : `graphity_runtime.py` /
  `vault_memory.py` dans `jarvis-starter`.
- Rester decouple d'une installation "source editable" d'OpenJarvis :
  OpenJarvis est installe via le script officiel (`install.ps1`), donc le
  pont ne doit rien modifier dans l'arborescence installee -- uniquement de
  la configuration (`config.toml`, section `[tools.mcp]`).

## Non-objectifs

- Pas de migration des autres outils jarvis-starter (write_file, run_command,
  search_web, etc.) -- deja couverts nativement par OpenJarvis, sujet d'un
  futur sous-projet "configuration".
- Pas de remplacement de la GUI Tkinter par la GUI Tauri d'OpenJarvis --
  futur sous-projet separe.
- Pas de changement au moteur Graphify lui-meme (`graphity_runtime.py`) --
  on l'enveloppe, on ne le modifie pas.
- Pas d'auto-decouverte de plugins : le pont est un serveur MCP explicitement
  declare dans `config.toml`, pas un mecanisme generique de chargement de
  plugins Python.

## Architecture

Nouveau module autonome `jarvis-starter/graphify_mcp_server.py` (stdio MCP
server, meme famille que les autres serveurs MCP deja utilises dans cet
environnement), qui importe et appelle directement les fonctions existantes
de `graphity_runtime.py`/`vault_memory.py` -- aucune duplication de logique.

```text
OpenJarvis (agent loop)
        |
        v  MCP (stdio), declare dans configs/openjarvis/config.toml [tools.mcp]
        v
graphify_mcp_server.py  (jarvis-starter/)
        |
        v  import direct, aucun sous-processus supplementaire
        v
graphity_runtime.py / vault_memory.py  (deja existants, inchanges)
        |
        v
.graphify/ (vault Obsidian STARBOXE-Notes -- graphe deja construit)
```

## Composants

### `graphify_mcp_server.py`

Serveur MCP minimal (protocole stdio, comme les serveurs MCP deja presents
dans `~/.mcp.json` pour ce poste) exposant deux tools :

- **`graphify_recall`** -- parametre `query: str`. Appelle directement
  `GraphityRuntime.memory.recall(query)` (le meme chemin de code que
  `jarvis.py:execute_agent_tool` pour `graphity_recall` aujourd'hui) et
  retourne le texte resultant.
- **`graphify_remember`** -- parametre `text: str`. Appelle
  `GraphityRuntime.memory.remember(text)`, meme principe.

Le serveur instancie `GraphityRuntime(data_dir, vault_path)` une seule fois
au demarrage, avec `vault_path` par defaut = `DEFAULT_VAULT_PATH` (deja
defini dans `vault_memory.py`) et `data_dir` = un sous-dossier dedie (ex.
`jarvis-starter/data/graphify-mcp/`), separe du `data_dir` habituel de
`jarvis.py` pour eviter tout conflit d'acces concurrent au meme etat.

### Configuration OpenJarvis (`configs/openjarvis/config.toml`)

Ajout d'une entree dans `[tools.mcp]` pointant vers
`graphify_mcp_server.py` (commande `python`, chemin absolu du script,
working directory = `jarvis-starter/`). Le moteur d'inference reste
configure sur Ollama / qwen2.5:7b (deja le defaut actuel de
`jarvis-starter`, deja gere nativement par OpenJarvis).

## Flux de donnees

```
Utilisateur (via OpenJarvis) : "qu'est-ce que je sais deja sur le sujet X ?"
  -> agent OpenJarvis decide d'appeler l'outil MCP graphify_recall
  -> graphify_mcp_server.py recoit l'appel MCP
  -> GraphityRuntime.memory.recall("X") -> texte extrait du graphe 51k noeuds
  -> resultat renvoye a l'agent OpenJarvis comme observation d'outil
  -> reponse finale de l'agent
```

## Gestion d'erreurs

- Si le vault Obsidian ou le dossier `.graphify/` est absent/inaccessible au
  demarrage du serveur MCP : erreur explicite au demarrage (fail-fast), pas
  de degradation silencieuse -- coherent avec le fait que sans le graphe, cet
  outil n'a aucune utilite.
- Si `recall`/`remember` levent une exception interne (deja geree cote
  `GraphityRuntime` aujourd'hui, a verifier lors de l'implementation) : le
  serveur MCP la convertit en reponse d'erreur MCP standard, jamais un crash
  du process serveur (qui casserait toute la session OpenJarvis, pas
  seulement cet appel d'outil).

## Tests

Nouveau fichier `jarvis-starter/tests/test_graphify_mcp_server.py`, pytest,
sur le meme modele que les tests Graphity existants
(`tests/test_graphity_runtime.py`) :

- `graphify_recall` sur une requete connue retourne du contenu reel (test
  contre le vrai graphe existant, pas un mock -- coherent avec le principe
  deja applique dans `test_jarvis_code_tools.py` d'avoir au moins un test
  d'integration reel plutot que 100% de mocks).
- `graphify_remember` ecrit bien un nouveau fait recuperable ensuite par un
  `graphify_recall` sur le meme sujet (aller-retour reel).
- Demarrage du serveur avec un `vault_path` inexistant -> erreur explicite,
  pas de crash silencieux ni de demarrage reussi dans un etat casse.

## Verification end-to-end

Au-dela des tests unitaires : lancer OpenJarvis (`jarvis`) avec la config
mise a jour, poser une question dont la reponse necessite le graphe
Graphify, confirmer que l'agent appelle bien l'outil MCP et retourne une
reponse coherente avec le contenu reel du vault.

## Hors scope / suite possible

- Configuration des outils natifs OpenJarvis deja equivalents (file_write,
  shell_exec, web_search, text_to_speech, approval_store) -- sous-projet
  "configuration" separe.
- Remplacement de la GUI Tkinter par la GUI Tauri d'OpenJarvis.
- Migration des rappels proactifs (`reminders.py`) -- a rapprocher de
  `proactive_tools.py` cote OpenJarvis dans un futur sous-projet.
- Migration de l'integration Gmail -- aucun equivalent natif identifie cote
  OpenJarvis a ce jour, a re-evaluer.
