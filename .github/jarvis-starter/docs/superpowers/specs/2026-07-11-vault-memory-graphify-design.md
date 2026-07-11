# Mémoire réelle : brancher Jarvis sur le vault Obsidian via graphify

## Contexte

Jarvis a aujourd'hui deux systèmes internes lié à "graphity", tous deux
deconnectés du vault Obsidian réel de l'utilisateur :

1. `GraphityMemory` (`graphity_runtime.py`) : un mini-index maison
   entité-cooccurrence, stocke ses evenements dans
   `<data_dir>/graphity/memory/events.jsonl` et un graphe JSON local. Aucun
   lien avec Obsidian.
2. `GraphityRuntime` : simule une API type "Vertex AI Agent Engine" avec
   des "revisions" (deux personas pre-configures : `v1-fast-local` et
   `v2-graph-memory`) et un routage A/B (`traffic split`). **Code mort** :
   `GraphityRuntime` est importe dans `jarvis.py` mais jamais instancie, et
   aucune branche de `handle()` ou `execute_agent_tool()` ne traite les
   commandes/outils `graphity *` qui sont pourtant documentes dans
   `HELP_TEXT` et `AGENTIC_SYSTEM_INSTRUCTIONS`. Résultat observe : les
   commandes "graphity" ne font rien (ou partent en texte libre vers le
   LLM), ce qui a motive cette spec.

Par ailleurs, l'utilisateur a un vault Obsidian existant et actif :
`C:\Users\aiell\Documents\STARBOXE-Notes`, deja indexe par la vraie CLI
`graphify` (paquet npm global, `.graphify/graph.json` present, 52 Ko,
dernière construction perimee depuis plus d'un mois). `graphify` propose
notamment `query <question>` (BFS sur le graphe) et `update <path>`
(reconstruction). Confirme fonctionnel par test direct :
`graphify query "Jarvis" --graph <vault>/.graphify/graph.json` renvoie
`"No matching nodes found."` (texte simple, pas de JSON).

Le nom "graphity" (moteur maison de Jarvis) et "graphify" (vrai outil du
vault) se ressemblent enormement mais n'ont aucun lien — source de
confusion identifiee pendant le brainstorming.

## Objectifs

- Le rappel memoire de Jarvis (`graphity_recall`, `graphity memo <recherche>`)
  interroge le vrai graphe `graphify` du vault, pas un index maison.
- Les notes creees par Jarvis (`graphity_remember`, et a terme `note`)
  s'ecrivent dans le vault Obsidian, dans un dossier dedie a Jarvis, et
  declenchent une reconstruction du graphe pour rester a jour.
- Le systeme de revisions/A-B testing (`GraphityRuntime`) est enfin
  instancie et cable dans `jarvis.py` : les commandes/outils deja
  documentes deviennent reellement fonctionnels.
- Aucune degradation silencieuse : si `graphify` est absent du PATH ou le
  vault introuvable, Jarvis renvoie une erreur claire plutot qu'un faux
  resultat.

## Non-objectifs

- Pas de synchronisation bidirectionnelle avancee (Jarvis ne modifie jamais
  les notes existantes de l'utilisateur, seulement son propre dossier).
- Pas de refonte de l'extraction d'entites de `graphify` lui-meme (outil
  externe, deja construit et maintenu separement).
- Pas de nettoyage du reste du vault (642 fichiers, structure
  `04_Agents_IA/` existante) — on ajoute un dossier, on n'y touche pas.
- Pas de changement au provider LLM (OpenAI/Ollama) ni a la limite de 3
  tours de la boucle agentic.

## Architecture

Nouveau module `jarvis-starter/vault_memory.py`, sur le meme modele
d'isolation que `graphity_runtime.py`/`web_tools.py` (spec precedente) :
logique pure, testable via mock de `subprocess.run`, aucun effet de bord
d'interface utilisateur.

`graphity_runtime.py` est modifie : `GraphityMemory` (le mini-index maison)
est retire ; `GraphityRuntime.memory` devient une instance de
`vault_memory.VaultMemory` a la place. Le reste de `GraphityRuntime`
(revisions, traffic split, routage) est conserve tel quel — c'est une
fonctionnalite legitime, seulement jamais branchee.

```text
Jarvis.__init__()
  -> self.graphity = GraphityRuntime(data_dir / "graphity", vault_path=...)

Jarvis.run_agentic(user_text)
  -> self.graphity.invoke(user_text, executor=lambda revision, graph_context: ...)
       -> route_revision() choisit v1-fast-local ou v2-graph-memory
       -> memory.recent_context(user_text) -> vault_memory.recall(user_text)
       -> executor construit le prompt avec revision.instructions + graph_context
       -> memory.remember(...) -> vault_memory.remember(...)

Jarvis.handle() / execute_agent_tool()
  -> commandes/outils "graphity *" cables vers self.graphity
```

## Composants

### `vault_memory.VaultMemory`

Construite avec `vault_path: Path` (issu de `JARVIS_VAULT_PATH`) et
`jarvis_folder: str = "04_Agents_IA/Jarvis"`.

- `remember(text: str) -> str` :
  1. Verifie que `vault_path` existe (sinon retourne
     `"vault_memory: vault introuvable a <path>"`).
  2. Ecrit une note markdown horodatee dans
     `<vault_path>/04_Agents_IA/Jarvis/YYYY-MM-DD_HHMMSS.md` (frontmatter
     minimal : `# Jarvis note` + timestamp + texte).
  3. Lance `graphify update <vault_path>` via `subprocess.run(..., timeout=30)`.
  4. Retourne `"note enregistree dans le vault"` ou un message d'erreur
     explicite (graphify introuvable dans le PATH, timeout, code de sortie
     non nul).
- `recall(query: str) -> str` :
  1. Verifie l'existence de `<vault_path>/.graphify/graph.json` (sinon
     retourne `"vault_memory: graphe absent, lance 'graphify <vault>' pour
     l'indexer"`).
  2. Lance `graphify query "<query>" --graph <vault_path>/.graphify/graph.json`
     via `subprocess.run(..., timeout=30, capture_output=True)`.
  3. Retourne `stdout` tel quel (deja un texte lisible, confirme par test
     manuel), tronque a 4000 caracteres par securite.
  4. Erreurs (graphify absent, timeout, code non nul) -> message clair,
     jamais d'exception qui remonte.

Aucune ecriture destructrice : `VaultMemory` ne touche jamais un fichier
hors de `04_Agents_IA/Jarvis/`.

### `GraphityRuntime` (modifications)

- Le champ `memory` est maintenant un `VaultMemory` au lieu d'un
  `GraphityMemory`. `invoke()` ne change pas de signature.
- `GraphityMemory` et sa classe associee sont supprimees de
  `graphity_runtime.py` (plus de doublon d'index local).

### Integration dans `jarvis.py`

- `Jarvis.__init__` : lit `JARVIS_VAULT_PATH` (env, defaut
  `C:\Users\aiell\Documents\STARBOXE-Notes`), instancie
  `self.graphity = GraphityRuntime(data_dir / "graphity")` avec la memoire
  branchee sur ce chemin.
- `run_agentic` : remplace l'appel direct a `self.ai.ask(...)` par un
  passage via `self.graphity.invoke(user_text, executor)`, ou `executor`
  encapsule la boucle agentic existante (tool_calls JSON) en injectant
  `revision.instructions` en tete du prompt systeme et `graph_context`
  (sortie de `vault_memory.recall`) dans `build_agent_prompt`.
- `handle()` : nouvelle branche `command.startswith("graphity ")` qui
  route vers :
  - `graphity revisions` -> `self.graphity.list_revisions()`
  - `graphity traffic` -> `self.graphity.describe_traffic()`
  - `graphity split 1=50 2=50` -> parse `cle=valeur` -> `set_manual_split`
  - `graphity latest` -> `self.graphity.set_always_latest()`
  - `graphity memo <recherche>` -> `self.graphity.memory.recall(<recherche>)`
- `execute_agent_tool` : nouvelles branches `graphity_recall` ->
  `self.graphity.memory.recall(args["query"])` et `graphity_remember` ->
  `self.graphity.memory.remember(args["text"])`.
- `env.template` : ajoute `JARVIS_VAULT_PATH=` (commentaire : chemin du
  vault Obsidian, vide = valeur par defaut codee en dur).

## Flux de données

```text
Utilisateur: "agent souviens-toi que je veux relancer la campagne SEO en aout"
  -> planificateur LLM emet tool_calls: [graphity_remember]
  -> execute_agent_tool("graphity_remember", {"text": "..."})
  -> vault_memory.remember(...) ecrit
     STARBOXE-Notes/04_Agents_IA/Jarvis/2026-07-11_161200.md
  -> subprocess "graphify update <vault>" reconstruit le graphe
  -> observation renvoyee au planificateur -> reponse finale

Utilisateur: "graphity memo campagne SEO"
  -> handle() detecte prefixe "graphity "
  -> self.graphity.memory.recall("campagne SEO")
  -> subprocess "graphify query 'campagne SEO' --graph ..."
  -> texte du graphe affiche directement (pas d'appel LLM necessaire)
```

## Gestion d'erreurs

- Toute methode de `VaultMemory` retourne une `str`, jamais d'exception :
  `graphify` absent du PATH (`FileNotFoundError` sur `subprocess.run`),
  timeout (30s), code de sortie non nul, vault ou graphe absent — tous
  convertis en message prefixe `"vault_memory: ..."`.
- Pas de fallback silencieux vers un ancien systeme : si le vrai graphify
  echoue, Jarvis le dit clairement plutot que de renvoyer un resultat vide
  ou trompeur.
- Le systeme de revisions garde son comportement actuel en cas d'etat
  invalide (`GraphityStateError` deja gere par les appelants existants).

## Tests

- `jarvis-starter/tests/test_vault_memory.py` (pytest, mock
  `subprocess.run` — aucun appel reseau ni CLI reel) :
  - `remember` : ecriture reussie + rebuild ok, vault introuvable,
    graphify absent (`FileNotFoundError`), timeout, code de sortie non nul.
  - `recall` : requete reussie (stdout renvoye), graphe absent, graphify
    absent, timeout.
- `jarvis-starter/tests/test_graphity_runtime.py` (pytest, aucun test
  existant aujourd'hui) :
  - Bootstrap des deux revisions par defaut.
  - `set_manual_split` valide (somme=100) et invalide (somme != 100 ->
    `GraphityStateError`).
  - `route_revision` en mode `always_latest` vs `manual` (deterministe via
    injection d'un `random.randint` mocke).
  - `resolve_revision` par numero/label/nom.
- Reprend `requirements-dev.txt` (`pytest>=8.0`) de la spec precedente,
  pas de nouvelle dependance.

## Hors scope / suite possible

- Nettoyage/relecture du GRAPH_REPORT.md perime (>1 mois) — hors scope,
  le premier `remember` le rafraichira naturellement.
- Extraction d'entites plus riche cote Jarvis (aujourd'hui delegue
  entierement a `graphify`, qui gere deja cela pour tout le vault).
- Reconciliation si l'utilisateur edite manuellement les notes dans
  `04_Agents_IA/Jarvis/` pendant que Jarvis tourne (pas de watch/lock).
- Categories d'outils non retenues dans les specs precedentes
  (fichiers/dossiers generaux, controle systeme, calendrier) — toujours
  a reprendre separement.
