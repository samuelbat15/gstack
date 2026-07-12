# Feuille de route Jarvis — vision complete "Iron Man"

Cette feuille de route a ete etablie le 2026-07-12 pour capturer la vision
complete d'un assistant Jarvis comparable a celui d'Iron Man. Elle liste
tout ce qui manque au-dela de ce qui existe deja dans `jarvis-starter/`.
C'est un document de reference — chaque point ci-dessous devient sa propre
spec + plan + implementation quand on decide de s'y attaquer, un morceau a
la fois (voir `docs/superpowers/specs/` et `docs/superpowers/plans/`).

## Deja construit (jarvis-starter au 2026-07-12)

- LLM local (Ollama, qwen2.5:7b) + cloud (OpenAI, OpenRouter)
- Interaction texte + vocale optionnelle (speech_recognition/pyttsx3)
- Rappels programmes + mode `--daemon`
- Memoire long terme via le vrai graphe `graphify` sur le vault Obsidian
- Systeme de revisions/A-B testing (`graphity revisions/traffic/split`)
- Boucle agentic robustifiee (dedup, 6 tours, synthese forcee)
- Lanceur bureau (icone + `.bat`)

## Ce qui manque (priorite non fixee — a decider au fur et a mesure)

1. **Cerveau central / orchestrateur** — aujourd'hui Jarvis, MMA Analyzer,
   Dashboard, Graphity, Memory et Notifications sont des projets separes
   sans routage central entre eux.
2. **Vision temps reel** — analyser en continu webcam, bureau Windows,
   jeux, OBS, cameras IP (aujourd'hui : analyse video ponctuelle via
   MMA Analyzer uniquement).
3. **Memoire intelligente** — recherche semantique, graphe de
   preferences/habitudes, pas juste des notes chronologiques.
4. **Dashboard temps reel** — CPU/RAM/GPU/VRAM/temperature/reseau/logs/
   tokens/modele utilise/pipeline en direct, style "Mission Control".
5. **Interface conversationnelle non-bloquante** — reflexion visible,
   execution visible, corrections en direct, sans attente silencieuse.
6. **Proactivite avancee** — alertes conditionnelles (GPU qui chauffe,
   serveur arrete, site hors ligne, mail recu), au-dela des rappels a
   heure fixe deja livres.
7. **Agents specialises** — Coach, Developpeur, Marketing, Musique,
   Vision, Finance, MMA, Automation, Recherche, Creatif — chacun avec son
   propre contexte, au lieu d'un seul planificateur generaliste.
8. **Controle Windows** — ouvrir/fermer logiciels, cliquer, taper,
   deplacer la souris, captures d'ecran, OCR, reconnaissance de fenetre,
   controle navigateur.
9. **Vision + voix combinees** — "qu'est-ce qu'il y a sur mon ecran ?" ->
   regarder -> repondre -> agir -> corriger.
10. **Dashboard vivant** — version enrichie du point 4, avec indicateurs
    d'etat en mouvement (Listening/Watching/Thinking/Executing/Finished).
11. **Personnalite** — humour, "emotions" simulees, voix unique, style,
    memoire des conversations passees, habitudes.
12. **Automation complete en boucle** — observer -> detecter -> reflechir
    -> agir -> prevenir, sans attendre une commande explicite.
13. **Systeme de competences/plugins** — modules independants
    (`skills/vision`, `skills/music`, `skills/gmail`, `skills/docker`,
    `skills/windows`, etc.) au lieu d'outils codes en dur dans `jarvis.py`.
14. **Interface visuelle "Iron Man"** — animations, cartes interactives,
    chronologie des actions, graphiques, controle voix + souris unifie.

## Discipline de travail

Chaque point ci-dessus est un projet a part entiere (souvent plusieurs
jours de travail reel). La regle etablie cette session : brainstorming ->
spec ecrite -> plan TDD -> implementation -> verification en conditions
reelles -> commit, un morceau a la fois. Ne pas essayer d'en attaquer
plusieurs simultanement — ca a deja produit du code fragile par le passe
(voir la boucle agentic a 3 tours sans dedup, corrigee le 2026-07-11).
