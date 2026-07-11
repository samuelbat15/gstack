# Outils web pour la boucle agentic de Jarvis

## Contexte

Jarvis (`jarvis-starter/jarvis.py`) a une boucle agentic (`run_agentic`) qui
appelle un planificateur LLM (OpenAI ou Ollama) capable d'invoquer 9 outils
locaux : `get_time`, `get_status`, `add_note`, `list_notes`, `search_web`,
`open_site`, `launch_app`, `graphity_recall`, `graphity_remember`.

Le manque identifie : Jarvis peut ouvrir une recherche web dans le navigateur,
mais ne peut ni lire le contenu d'une page, ni repondre a une question factuelle
rapide (meteo) sans passer par un navigateur. Cette spec ajoute deux outils :
lire/resumer une page web, et consulter la meteo.

Cette spec couvre uniquement la couche "raisonnement agentic" (voir README,
section Architecture reelle, etape 4). Les couches perception, memoire long
terme, TTS et proactivite restent hors scope et seront traitees separement.

## Objectifs

- Ajouter un outil `fetch_url` : recupere une page web, en extrait le texte
  utile, le renvoie tronque au planificateur pour resume/reponse.
- Ajouter un outil `get_weather` : donne la meteo actuelle et une courte
  prevision pour une ville, sans cle API.
- Garder la coherence avec le pattern existant : chaque outil agentic a aussi
  une commande directe equivalente (comme `cherche` / `search_web`).
- Garder confirmation `[o/N]` systematique avant execution, meme pour ces
  actions en lecture seule (choix explicite : coherence avec la regle d'or du
  README, "l'IA propose, le code verifie, l'utilisateur autorise").
- Zero nouvelle cle API / secret a gerer.

## Non-objectifs

- Pas de cache de pages ou de resultats meteo.
- Pas d'extraction "article propre" de niveau production (type Readability) —
  qualite "suffisante pour un resume", pas parfaite.
- Pas de changement a la limite de 3 tours de la boucle agentic existante.
- Pas de nouveaux providers LLM.

## Architecture

Nouveau module `jarvis-starter/web_tools.py`, sur le meme modele que
`graphity_runtime.py` : logique pure, testable sans dependre de la classe
`Jarvis` ni d'un vrai reseau. `jarvis.py` importe ce module et l'appelle
depuis `execute_agent_tool` (chemin agentic) et depuis `handle` (commandes
directes), exactement comme `search_web`/`open_allowed_target` aujourd'hui.

```text
Jarvis.handle() / Jarvis.execute_agent_tool()
        |
        v
  web_tools.fetch_url_text(url, max_chars)      -> str (texte extrait ou erreur)
  web_tools.get_weather_text(location)           -> str (texte francais ou erreur)
        |
        v
  urllib.request (stdlib) vers la page cible / Open-Meteo
```

Le flux de confirmation reste dans `Jarvis` (pas dans `web_tools.py`), pour
que le module reste une fonction pure sans effet de bord ni input().

## Composants

### `web_tools.fetch_url_text(url: str, max_chars: int = 6000) -> str`

1. Valide que `url` commence par `http://` ou `https://` (sinon erreur).
2. Telecharge via `urllib.request.urlopen(url, timeout=15)`, taille max lue
   plafonnee a 2 Mo (`response.read(2_000_000)`).
3. Verifie `Content-Type` contient `text/html` (sinon message d'erreur
   explicite plutot que planter sur du binaire).
4. Extrait le texte avec `html.parser.HTMLParser` : ignore le contenu de
   `<script>`, `<style>`, `<nav>`, `<header>`, `<footer>` ; garde le texte de
   `<title>` et des `<p>` (et `<li>` en secours si aucun `<p>` trouve).
5. Normalise les espaces, tronque a `max_chars`, ajoute un marqueur
   `"[tronque]"` si troncature.
6. Retourne le texte ; en cas d'erreur (timeout, HTTP != 200, contenu non
   HTML, exception reseau), retourne une chaine `"fetch_url: erreur - ..."`
   au lieu de lever une exception (coherent avec le pattern des clients IA
   existants, qui retournent toujours une string).

### `web_tools.get_weather_text(location: str) -> str`

1. Geocodage : `GET https://geocoding-api.open-meteo.com/v1/search?name=<location>&count=1&language=fr`.
   Si aucun resultat, retourne `"get_weather: ville introuvable"`.
2. Prevision : `GET https://api.open-meteo.com/v1/forecast?latitude=..&longitude=..&current=temperature_2m,weather_code,wind_speed_10m&forecast_days=1&language=fr`.
3. Traduit le `weather_code` (code WMO) en description francaise courte via
   une table de correspondance statique dans `web_tools.py` (ex: 0 -> "ciel
   degage", 61 -> "pluie faible", etc., ~20 entrees couvrant les codes
   courants).
4. Retourne une phrase du type :
   `"Meteo a Paris : 18 degres, pluie faible, vent 12 km/h."`
5. Erreurs (reseau, timeout, JSON invalide) -> `"get_weather: erreur - ..."`.

### Integration dans `jarvis.py`

- `AGENTIC_SYSTEM_INSTRUCTIONS` : ajoute les entrees
  `fetch_url {"url": "..."}` et `get_weather {"location": "ville"}` a la
  liste des outils autorises. Pas de champ "question" separe : le
  planificateur a deja la demande originale de l'utilisateur dans son
  contexte, un champ dedie serait redondant.
- `execute_agent_tool` : ajoute les branches `fetch_url` et `get_weather`,
  chacune passant par `self.confirm(...)` avant l'appel reseau, exactement
  comme `open_site`/`launch_app` le font deja.
- `handle` : ajoute les prefixes de commande directe `lis` (fetch_url) et
  `meteo` (get_weather), sur le meme modele que `cherche`/`ouvre`.
- `HELP_TEXT` : documente les deux nouvelles commandes et les deux nouveaux
  outils agentic.
- `looks_like_local_command` : ajoute `lis` et `meteo` aux prefixes
  reconnus (pour l'annulation de confirmation en attente, comme les autres
  commandes directes).

## Flux de donnees

```
Utilisateur: "lis https://exemple.com/article"
  -> Jarvis.handle() detecte prefixe "lis "
  -> confirm("lire la page https://exemple.com/article") -> [o/N]
  -> web_tools.fetch_url_text(url) -> texte extrait (<=6000 car)
  -> texte transmis a self.ai.ask(...) comme contexte pour un resume
  -> reponse finale parlee/affichee

Utilisateur (mode agentic): "resume moi la page X puis dis moi s'il va pleuvoir a Paris"
  -> planificateur LLM emet tool_calls: [fetch_url, get_weather]
  -> chaque appel passe par confirm() individuellement
  -> observations accumulees -> tour suivant du planificateur -> reponse finale
```

## Gestion d'erreurs

- Toute fonction de `web_tools.py` retourne toujours une `str` (jamais
  d'exception qui remonte a l'appelant) : timeout, DNS invalide, HTTP 4xx/5xx,
  contenu non-HTML, JSON malforme sont tous convertis en message d'erreur
  lisible, prefixe par le nom de l'outil (coherent avec le reste de
  `execute_agent_tool`, ex. `"open_site: cible manquante."`).
- Si l'utilisateur refuse la confirmation, comportement identique a
  `open_allowed_target` aujourd'hui : `"annule par l'utilisateur."`.
- Taille de reponse plafonnee (2 Mo telecharges, 6000 caracteres retournes)
  pour eviter qu'une page enorme ne sature le contexte du prochain appel LLM.

## Tests

Nouveau fichier `jarvis-starter/tests/test_web_tools.py`, pytest, zero appel
reseau reel : `urllib.request.urlopen` est remplace par un mock (retourne un
objet fichier en memoire avec `.read()`, `.status` ou `.getcode()`, et
`.headers.get_content_type()`).

Cas couverts :

- `fetch_url_text` : extraction reussie (HTML avec `<p>` multiples),
  troncature au-dela de `max_chars`, URL invalide (pas de schema http/https),
  Content-Type non-HTML, HTTPError (ex. 404), timeout/URLError.
- `get_weather_text` : ville trouvee + prevision reussie, ville introuvable
  (geocodage vide), erreur reseau sur l'appel prevision, code meteo inconnu
  (fallback texte generique plutot que crash).

Nouveau `jarvis-starter/requirements-dev.txt` :

```text
pytest>=8.0
```

Le README est mis a jour avec une section "Lancer les tests" :

```powershell
pip install -r requirements-dev.txt
pytest
```

## Hors scope / suite possible

- Extraction d'article "propre" (retirer menus/pubs plus finement) si le
  texte brut s'avere trop bruite en usage reel.
- Cache court terme pour eviter de refaire un appel meteo identique en
  quelques minutes.
- API meteo alternative si Open-Meteo ne couvre pas un besoin precis
  (alertes, historique).
- Autres categories d'outils identifiees mais non retenues cette fois :
  fichiers/dossiers, controle systeme/applications, calendrier/rappels — a
  reprendre dans une spec dediee.
