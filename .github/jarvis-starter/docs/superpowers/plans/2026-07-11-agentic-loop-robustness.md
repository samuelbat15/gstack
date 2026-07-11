# Fiabiliser la boucle agentic — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Corriger le bug observe en conditions reelles (boucle agentic qui
duplique un appel d'outil et n'arrive jamais a conclure) : deduplication
des appels identiques, limite de tours 3 -> 6, synthese finale forcee au
lieu du dump technique brut.

**Architecture:** Modification localisee de `Jarvis.run_agentic` +
nouvelle methode `Jarvis.force_final_synthesis` dans
`jarvis-starter/jarvis.py`. Premiere suite de tests pour `jarvis.py`
lui-meme (aucune n'existe encore sur cette branche).

**Tech Stack:** Python 3.11 (stdlib), pytest (nouveau sur ce fichier —
`vault_memory.py`/`graphity_runtime.py` n'existent pas encore sur cette
branche, cette infra de test est donc creee ici en premier).

---

## Fichiers concernes

- Modify: `jarvis-starter/jarvis.py:655-686` (`run_agentic`), ajout d'une
  nouvelle methode `force_final_synthesis`.
- Create: `jarvis-starter/requirements-dev.txt` — `pytest>=8.0`.
- Create: `jarvis-starter/pytest.ini` — `pythonpath = .`.
- Create: `jarvis-starter/tests/test_jarvis_agentic.py`.

---

### Task 1: Scaffolding de tests + déduplication des appels d'outils

**Files:**
- Create: `jarvis-starter/requirements-dev.txt`
- Create: `jarvis-starter/pytest.ini`
- Test: `jarvis-starter/tests/test_jarvis_agentic.py`
- Modify: `jarvis-starter/jarvis.py:655-686` (`run_agentic`)

- [ ] **Step 1: Créer les fichiers de config de test**

`jarvis-starter/requirements-dev.txt`:

```text
pytest>=8.0
```

`jarvis-starter/pytest.ini`:

```ini
[pytest]
pythonpath = .
```

- [ ] **Step 2: Installer les dépendances de dev**

Run (depuis `jarvis-starter/`):

```powershell
pip install -r requirements-dev.txt
```

Expected: installation de `pytest` sans erreur.

- [ ] **Step 3: Écrire les tests qui échouent pour la déduplication**

`jarvis-starter/tests/test_jarvis_agentic.py`:

```python
from __future__ import annotations

import json

from jarvis import Config, Jarvis


class ScriptedAI:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.enabled = True
        self.calls: list[tuple[str, str]] = []

    def ask(self, prompt: str, memory_context: str = "", instructions: str = "") -> str:
        self.calls.append((prompt, instructions))
        return self.responses.pop(0)


def make_jarvis(tmp_path) -> Jarvis:
    config = Config(assistant_name="Jarvis", confirm_actions=False, sites={}, apps={})
    return Jarvis(config=config, voice=False, data_dir=tmp_path)


def agent_turn(tool_calls, final=""):
    return json.dumps({"thought": "test", "tool_calls": tool_calls, "final": final})


class TestDeduplication:
    def test_duplicate_call_not_re_executed(self, tmp_path):
        jarvis = make_jarvis(tmp_path)
        jarvis.ai = ScriptedAI(
            [
                agent_turn([{"tool": "add_note", "args": {"text": "acheter du pain"}}]),
                agent_turn([{"tool": "add_note", "args": {"text": "acheter du pain"}}]),
                agent_turn([], final="Fait."),
            ]
        )

        result = jarvis.run_agentic("note que je dois acheter du pain")

        assert result == "Fait."
        notes = jarvis.memory.recent_notes()
        assert notes.count("acheter du pain") == 1

    def test_different_args_both_executed(self, tmp_path):
        jarvis = make_jarvis(tmp_path)
        jarvis.ai = ScriptedAI(
            [
                agent_turn([{"tool": "add_note", "args": {"text": "note A"}}]),
                agent_turn([{"tool": "add_note", "args": {"text": "note B"}}]),
                agent_turn([], final="Fait."),
            ]
        )

        jarvis.run_agentic("deux notes")

        notes = jarvis.memory.recent_notes()
        assert "note A" in notes
        assert "note B" in notes

    def test_stops_immediately_on_first_final(self, tmp_path):
        jarvis = make_jarvis(tmp_path)
        jarvis.ai = ScriptedAI([agent_turn([], final="Bonjour")])

        result = jarvis.run_agentic("salut")

        assert result == "Bonjour"
        assert len(jarvis.ai.calls) == 1
```

- [ ] **Step 4: Vérifier que les tests échouent**

Run:

```powershell
python -m pytest tests/test_jarvis_agentic.py -v
```

Expected: `test_duplicate_call_not_re_executed` FAIL (2 occurrences de
"acheter du pain" au lieu d'1) ; les deux autres tests passent déjà (le
comportement existant les satisfait par accident — c'est attendu, ils
servent de garde-fou de non-régression).

- [ ] **Step 5: Implémenter la déduplication dans `run_agentic`**

Remplacer la méthode `run_agentic` actuelle dans `jarvis-starter/jarvis.py` :

```python
    def run_agentic(self, user_text: str) -> str:
        if not self.ai.enabled:
            return LOCAL_ONLY_MESSAGE

        observations: list[str] = []
        seen_calls: set[str] = set()
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

        return "J'ai atteint la limite de boucle agentic. Voici les observations:\n" + "\n".join(observations)
```

(La limite `range(3)` et le message de fin de boucle seront changés dans
la Task 2 — cette étape ajoute uniquement la déduplication pour garder
chaque étape testable isolément.)

- [ ] **Step 6: Vérifier que tous les tests passent**

Run:

```powershell
python -m pytest tests/test_jarvis_agentic.py -v
```

Expected: 3 passed.

- [ ] **Step 7: Commit**

```powershell
git add jarvis-starter/requirements-dev.txt jarvis-starter/pytest.ini jarvis-starter/tests/test_jarvis_agentic.py jarvis-starter/jarvis.py
git commit -m "fix: deduplicate repeated agentic tool calls with identical arguments"
```

---

### Task 2: Limite de 6 tours + synthèse finale forcée

**Files:**
- Modify: `jarvis-starter/jarvis.py` (`run_agentic`, nouvelle méthode `force_final_synthesis`)
- Modify: `jarvis-starter/tests/test_jarvis_agentic.py`

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter à `jarvis-starter/tests/test_jarvis_agentic.py` :

```python
class TestSynthesis:
    def test_six_turns_then_forced_synthesis(self, tmp_path):
        jarvis = make_jarvis(tmp_path)
        looping_turn = agent_turn([{"tool": "get_time", "args": {}}])
        jarvis.ai = ScriptedAI(
            [looping_turn] * 6 + ["Il est probablement l'heure de conclure."]
        )

        result = jarvis.run_agentic("boucle sans fin")

        assert result == "Il est probablement l'heure de conclure."
        assert len(jarvis.ai.calls) == 7

    def test_force_final_synthesis_returns_answer(self, tmp_path):
        jarvis = make_jarvis(tmp_path)
        jarvis.ai = ScriptedAI(["Reponse de synthese."])

        result = jarvis.force_final_synthesis("demande initiale", ["obs 1", "obs 2"])

        assert result == "Reponse de synthese."

    def test_force_final_synthesis_falls_back_on_empty_answer(self, tmp_path):
        jarvis = make_jarvis(tmp_path)
        jarvis.ai = ScriptedAI([""])

        result = jarvis.force_final_synthesis("demande initiale", ["obs 1", "obs 2"])

        assert "Je n'ai pas reussi a conclure" in result
        assert "obs 1" in result
        assert "obs 2" in result
```

- [ ] **Step 2: Vérifier que les tests échouent**

Run:

```powershell
python -m pytest tests/test_jarvis_agentic.py -v
```

Expected: FAIL — `AttributeError: 'Jarvis' object has no attribute
'force_final_synthesis'` ; `test_six_turns_then_forced_synthesis` échoue
aussi (boucle encore limitée à 3 tours, `ScriptedAI` n'a que 7 réponses
programmées mais la boucle s'arrête avant en consommant mal la séquence).

- [ ] **Step 3: Implémenter `force_final_synthesis` et porter la limite à 6 tours**

Dans `jarvis-starter/jarvis.py`, remplacer la ligne :

```python
        for _ in range(3):
```

par :

```python
        for _ in range(6):
```

Remplacer la ligne finale de `run_agentic` :

```python
        return "J'ai atteint la limite de boucle agentic. Voici les observations:\n" + "\n".join(observations)
```

par :

```python
        return self.force_final_synthesis(user_text, observations)
```

Ajouter la nouvelle méthode juste après `run_agentic` :

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
        answer = self.ai.ask(prompt, instructions=SYSTEM_INSTRUCTIONS).strip()
        if answer:
            return answer
        return "Je n'ai pas reussi a conclure. Voici les observations:\n" + observation_block
```

- [ ] **Step 4: Vérifier que tous les tests passent**

Run:

```powershell
python -m pytest tests/test_jarvis_agentic.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```powershell
git add jarvis-starter/jarvis.py jarvis-starter/tests/test_jarvis_agentic.py
git commit -m "feat: raise agentic loop to 6 turns with forced final synthesis"
```

---

### Task 3: Vérification end-to-end avec OpenRouter réel

**Files:** aucun changement de code — validation uniquement.

- [ ] **Step 1: Lancer toute la suite de tests**

Run (depuis `jarvis-starter/`):

```powershell
python -m pytest -v
```

Expected: 9 passed, 0 failed.

- [ ] **Step 2: Reproduire le cas qui avait échoué en conditions réelles**

Run (nécessite `OPENROUTER_API_KEY` déjà présente dans l'environnement) :

```powershell
$env:JARVIS_PROVIDER = "openrouter"
$env:OPENROUTER_MODEL = "openrouter/free"
"agent note que je dois tester jarvis avec openrouter puis donne moi lheure`nmes notes`nquitte" | python jarvis.py --text
Remove-Item Env:\JARVIS_PROVIDER
Remove-Item Env:\OPENROUTER_MODEL
```

Expected: `mes notes` ne montre plus qu'**une seule** note pour cette
demande (au lieu de 3 précédemment), et la réponse de l'agent est une
phrase naturelle plutôt que le dump technique brut — même si le modèle
gratuit hésite encore sur plusieurs tours, la déduplication empêche la
note dupliquée et la synthèse forcée garantit une réponse propre au pire cas.

- [ ] **Step 3: Documenter dans le README si le comportement diffère de l'attendu**

Si le test manuel révèle un écart avec l'Expected du Step 2, ne pas
corriger silencieusement : documenter l'écart précis observé et demander
à l'utilisateur s'il veut un ajustement avant de considérer la tâche
terminée.
