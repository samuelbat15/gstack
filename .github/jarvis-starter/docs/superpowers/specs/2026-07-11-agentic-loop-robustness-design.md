# Fiabiliser la boucle agentic (dedup + synthese forcee)

## Contexte

Test en conditions reelles avec `openrouter/free` (voir session du
2026-07-11) : la commande `agent note que je dois tester jarvis avec
openrouter puis donne moi lheure` a fait boucler `run_agentic` sur ses 3
tours sans jamais conclure. Le modele a rappele `add_note` avec le meme
texte a chaque tour au lieu de constater qu'il l'avait deja fait, resultat
: 3 notes quasi identiques dans `data/notes.md` et le message d'echec
generique `"J'ai atteint la limite de boucle agentic..."` avec un dump
technique brut des observations.

Deux causes reelles identifiees :

1. La limite de 3 tours est trop courte pour une tache a 2 etapes des que
   le modele hesite ne serait-ce qu'une fois.
2. Rien n'empeche le planificateur de rejouer un outil deja execute avec
   les memes arguments — les observations precedentes sont dans le prompt,
   mais un petit modele gratuit ne les exploite pas de maniere fiable pour
   eviter la repetition.

## Objectifs

- Porter la limite de tours de 3 a 6.
- Detecter les appels d'outil identiques (meme nom + memes arguments) deja
  executes dans la meme invocation et ne pas les rejouer, en le signalant
  clairement au planificateur.
- Si la limite de tours est atteinte sans reponse finale, faire un dernier
  appel IA dedie (hors format JSON) pour synthetiser une reponse en
  francais a partir des observations, au lieu du dump technique actuel.
- Zero changement de provider : reste sur le protocole JSON-en-texte
  actuel, fonctionne identiquement sur OpenAI/Ollama/OpenRouter.

## Non-objectifs

- Pas de passage au function-calling natif (tool_calls structures des
  API) — evalue et ecarte pendant le brainstorming : gros chantier
  multi-provider pour un gain incertain face a un fix cible.
- Pas de changement au nombre d'outils disponibles ni a leur logique
  individuelle (`execute_agent_tool` ne change pas de comportement pour
  les cas non-dupliques).
- Pas de persistance de l'historique de deduplication entre plusieurs
  invocations de `run_agentic` (le `seen_calls` est local a un seul appel
  utilisateur, pas de memoire long terme des appels — ce role est deja
  couvert par la spec memoire vault separee).

## Architecture

Modification localisee a `jarvis-starter/jarvis.py`, methode
`Jarvis.run_agentic` et nouvelle methode privee
`Jarvis.force_final_synthesis`. Aucun nouveau fichier, aucune nouvelle
dependance.

```text
run_agentic(user_text)
  seen_calls = set()
  pour chaque tour (max 6):
    prompt = build_agent_prompt(user_text, observations)
    raw = ai.ask(prompt, AGENTIC_SYSTEM_INSTRUCTIONS)
    payload = extract_json_object(raw)
    si payload is None: return raw
    si pas de tool_calls: return final ou "Termine."
    pour chaque tool_call:
      signature = f"{tool_name}:{json.dumps(args, sort_keys=True)}"
      si signature deja vue: observation = "deja execute, ne pas repeter"
      sinon: executer, marquer signature comme vue
  si la boucle se termine sans return:
    return force_final_synthesis(user_text, observations)
```

## Composants

### `run_agentic` (modifie)

- `max_turns` passe de `3` (boucle `for _ in range(3)`) a `6`.
- Nouveau `seen_calls: set[str]` initialise avant la boucle.
- Pour chaque appel d'outil dans `tool_calls[:5]` : calcule une signature
  `f"{tool_name}:{json.dumps(args, sort_keys=True, ensure_ascii=False)}"`.
  Si deja presente dans `seen_calls`, n'execute PAS l'outil ; ajoute a la
  place l'observation :
  `f"{tool_name}: deja execute avec ces arguments, resultat inchange. N'appelle pas le meme outil avec les memes arguments deux fois."`
  Sinon, ajoute la signature a `seen_calls` puis execute normalement via
  `execute_agent_tool` (comportement inchange pour un appel non duplique).
- Si les 6 tours s'epuisent sans qu'un `final` non vide ait ete retourne,
  appelle `self.force_final_synthesis(user_text, observations)` au lieu de
  renvoyer directement le dump technique.

### `force_final_synthesis` (nouvelle methode)

```python
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
    answer = self.ai.ask(prompt, instructions=SYSTEM_INSTRUCTIONS)
    answer = answer.strip()
    if answer:
        return answer
    return "Je n'ai pas reussi a conclure. Voici les observations:\n" + observation_block
```

Utilise `SYSTEM_INSTRUCTIONS` (le prompt systeme conversationnel normal,
pas `AGENTIC_SYSTEM_INSTRUCTIONS`) puisqu'on ne veut plus de JSON a ce
stade, juste une reponse texte directe.

## Flux de donnees

```text
Utilisateur: "agent note X puis donne moi lheure"
  Tour 1: tool_calls=[add_note] -> execute, seen_calls={"add_note:{...}"}
  Tour 2: tool_calls=[add_note] (meme texte)
    -> signature deja vue -> observation "deja execute..." au lieu de re-executer
  Tour 3: tool_calls=[get_time] -> execute normalement
  Tour 4: final="Note ajoutee, il est 17h12." -> return direct

Cas degrade (modele ne conclut jamais en 6 tours):
  -> force_final_synthesis appelle l'IA une derniere fois hors-JSON
  -> reponse naturelle en francais au lieu du dump d'observations brutes
```

## Gestion d'erreurs

- `force_final_synthesis` retourne un texte de secours (dump des
  observations) si l'appel IA final echoue ou renvoie une chaine vide —
  jamais d'exception, comportement coherent avec le reste du fichier.
- Le comportement existant pour `payload is None` (reponse IA non-JSON)
  reste inchange : retour immediat du texte brut, sans consommer de tour
  supplementaire.

## Tests

Pas de suite de tests existante pour `jarvis.py` lui-meme (les tests des
specs precedentes couvrent `vault_memory.py`/`graphity_runtime.py`, pas
`Jarvis`). Cette spec introduit les premiers tests directs sur
`run_agentic` et `force_final_synthesis`, dans
`jarvis-starter/tests/test_jarvis_agentic.py`, en simulant `self.ai.ask`
avec un client IA factice pour eviter tout appel reseau reel.

Cas a couvrir :
- Un appel d'outil duplique (meme nom + memes arguments) n'est execute
  qu'une fois ; la deuxieme tentative recoit l'observation "deja
  execute...".
- Deux appels avec le meme nom d'outil mais des arguments differents sont
  tous les deux executes normalement (pas de faux positif sur la
  deduplication).
- La boucle s'arrete des qu'un `final` non vide est renvoye, sans
  attendre les 6 tours.
- Apres 6 tours sans `final`, `force_final_synthesis` est appelee et son
  resultat est retourne tel quel.
- `force_final_synthesis` retourne le texte de secours quand l'appel IA
  final renvoie une chaine vide.

## Hors scope / suite possible

- Passage a un vrai tool-calling natif si le protocole JSON-en-texte
  montre encore des limites apres ce fix (ecarte pour cette iteration,
  voir Non-objectifs).
- Deduplication persistante entre plusieurs invocations de `run_agentic`
  (couverte a terme par la memoire vault, spec separee).
- Ajustement dynamique de `max_turns` selon la complexite percue de la
  demande (actuellement une constante fixe = 6 pour toutes les demandes).
