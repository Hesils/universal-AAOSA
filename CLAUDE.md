# universal-AAOSA — CLAUDE.md

Runtime multi-agents à coordination bottom-up par claiming. Le graphe d'exécution émerge des décisions distribuées des agents — il n'est pas connu à l'avance. Agnostique au domaine.

Ce fichier ne porte que le **stable** (archi, stack, conventions, spécificités night-run). L'état vivant (avancement, dernière session, prochaine étape) vit dans le vault — chargé par `/prime`.

## Contexte externe

Charger si tu manques de contexte sur l'état, les décisions ou l'historique :

- **État courant + carte du projet** : `seconde_brain\wiki\Projects\universal-AAOSA\index.md` (+ `architecture.md`, `avancement.md`, `roadmap.md`, `stack.md`, `decisions.md`, `evals.md`, `observability.md`, `todo.md`, `sessions/`)
- **Specs, plans & invariants détaillés par version** (dans ce repo) : `docs/superpowers/specs/` (V2a/V2b/V2c/V3) · `docs/superpowers/plans/` · `docs/superpowers/epics/` · `docs/backlog/` (tickets techniques)
- **Charger l'état** : `/prime` (détecte ce repo via le frontmatter `repo:` de la fiche vault et lit l'état + la daily). Pas d'autoload automatique ici — `/prime` est le geste de démarrage.

**Cycle de vie via commandes globales** (déjà disponibles depuis ce repo, pas de config locale) : `/prime` · `/save` · `/night-run` · `/task`. Les commandes vivent dans `~/.claude/commands/` et pointent les skills AIOS/vault en chemin absolu.

## Architecture

Runtime de claiming distribué : les agents revendiquent les tâches qu'ils peuvent traiter, le graphe d'exécution émerge — il n'est pas planifié.

```
src/aaosa/
├── schemas/    task · claim · output · elo
├── core/       agent.py (claim + execute, boucle tool-use) · tool.py
├── claiming/   scoring · phase1 (déterministe) · phase2 (LLM) · prompts · dispatch
├── config/     loader.py (load_agents YAML)
├── cli/        app.py (Typer : run · campaign · report · dashboard · health-check — seul endroit qui printe) · incident_runs.py (helpers purs) · report.py
├── runtime/    llm_client · runner (run_task / run_chain / run_divided_task) · divider · aggregator
├── tracing/    events · tracer · analysis (classify_run) · formatter · store
├── demo/       agents(.yaml) · tasks · tools · run_health_check_v3 · incident/ (monde simulé + roster 7 agents / 3 domaines)
├── elo/        formula · updater · persistence
└── qa/         protocol · rule_based · health_check · criteria · spec · judge · spec_evaluator · triage · task_spec_generator · adaptive

dashboard/      app Flask d'observabilité (create_app factory · cache on-demand · collectors · API REST no-store · build_graph pur · frontend vanilla JS/SVG)
tests/          miroir de src/aaosa/ + tests/dashboard/
runs/           store unifié persisté (gitignored) · runs_demo/ = store curé VERSIONNÉ (exhibits démo)
docs/           superpowers/{specs,plans,epics} · demo/exhibits.md · backlog/
```

Détail complet (rôle par fichier, séparations par version) → vault `architecture.md` + specs in-repo.

**Pipelines** :
- V1 : `Task → filter_candidates → run_phase2 → dispatch → agent.execute → Output | DispatchResult`
- V2 (+QA/ELO) : `… → agent.execute → [QA evaluate] → [ELO update]` — `evaluator=None` = comportement V1
- V3 (graphe émergent) : `run_divided_task → divider.divide (LLM) → run_chain (tri Kahn) → aggregator.aggregate | court-circuit 1 sink | unassigned`
- CLI end-to-end : `aaosa run [--scenario main|roster_gap]` · `campaign --n N --runs-root <frais>` · `report` · `dashboard` · `health-check`

## Stack & commandes

- Python 3.14, `uv`, Pydantic 2.13, OpenAI SDK 2.38, Typer 0.26.7, pytest 9.0.3, pytest-asyncio, python-dotenv. Toujours le venv, jamais Python système. Toujours la dernière version stable possible d'un package.
- Tests : `.venv\Scripts\python -m pytest <fichier> -v`
- CLI projet-wide : `.venv\Scripts\aaosa run [--scenario main|roster_gap]` · `aaosa campaign --n N --runs-root <frais>` · `aaosa report [--runs-root]` · `aaosa health-check`. Requiert `.env` avec `OPENAI_API_KEY` (sauf `report`, offline).
- Dashboard : `.venv\Scripts\aaosa dashboard [--port] [--runs-root]` (= `python -m dashboard`, défaut http://127.0.0.1:5001).

## Conventions git

`master` est protégée : **PR obligatoire + CI verte requise** (pas de review d'approbation — solo dev). Aucun commit direct sur `master`, y compris les night-runs.

- **Nommage de branche** : `feat/<ticket>-<slug>`, `fix/<slug>`, `docs/<slug>`, `chore/<slug>`. `<ticket>` = l'ancre 🆔 à 3 caractères du board.
- **Flux** : branche → push → `gh pr create` → CI verte → **squash-merge** → tag auto si bump version → suppression de la branche.
- **Merge** : squash uniquement (historique `master` linéaire, une ligne lisible par feature ; le détail TDD survit dans la PR).
- **Versioning** : règle 95c (semver) — patch `x.x.X+1`, mineur `x.X+1.0`, majeur `X+1.0.0`. Le bump de `pyproject.toml` fait partie du diff de la PR quand justifié ; le tag `v{version}` est créé automatiquement par la CI sur push `master`.

## Night-run — spécificités projet

Artefacts night-run **centralisés côté AIOS** (l'AIOS est le point central et consolide tous les night_runs) : file `AIOS\context\night\<date>-<repo>.md`, cartes `context\night\runs\`, rapports `context\night-reports\`. Lancer/reviewer depuis ce repo via `/night-run` (résout le projet via `repo:`). Night = session **auto mode**, sécurité portée par le hook **night-guard global** (pas de `settings.local.json` ici).

Conventions à respecter pour tout ticket night-run de ce projet :

1. **Backend pur = pleinement nuit-compatible** (TDD, suite verte avant de clore). C'est le gros du projet.
2. **DoD « validé LLM réel » ≠ la nuit.** Tout ce qui exige un run `aaosa` réel consomme `OPENAI_API_KEY` (coût + non déterministe) → pas de sign-off LLM-réel en aveugle la nuit. DoD nuit = tests verts + (si pertinent) trace/run capturé dans la carte de résultat ; la validation LLM-réel finale est faite par Quentin au matin (review).
3. **Front (dashboard) = subagent-driven + `/impeccable`** ; validation navigateur = jamais la nuit, sign-off Quentin au matin.
4. **Tests via le venv** (`.venv\Scripts\python -m pytest`), jamais Python système.

## Patterns établis

- **Imports absolus uniquement** : `from aaosa.schemas.task import Task`, jamais relatifs
- **Timestamp UTC** : `Field(default_factory=lambda: datetime.now(timezone.utc))` — jamais `datetime.utcnow()` (deprecated Python 3.14)
- **Validator non-empty** : `@field_validator` + `@classmethod` ; **invariant cross-fields** : `@model_validator(mode="after")` retourne `self`
- **Héritage ConfigDict** : Pydantic v2 hérite `model_config` des parents — ne pas re-déclarer sauf override intentionnel ; `extra="forbid"` hérité via `_BaseEvent`
- **`agent_id` / `task_id`** : toujours depuis `self.id` / `task.id` dans `claim()`, jamais depuis la réponse LLM
- **Import circulaire** `agent.py ↔ prompts.py` : résolu par import local de `prompt_template` dans `claim()`
- **TDD subagent-driven** : tests avant l'impl, subagents séparés test-writers / code-writers / reviewer

## Séparations strictes à ne pas briser

Invariants transverses (détail par version → specs in-repo) :

- `fit_score` **n'est pas** injecté dans le prompt Phase 2 — l'agent raisonne sans son score système
- `passes_filter` et `fit_score` sont des **fonctions pures** sur (Agent, Task), pas des méthodes d'Agent
- Phase 1 = déterministe sans LLM / Phase 2 = cognitif avec LLM — ne jamais mélanger
- Tracer = **observer découplé** : le runtime émet, le tracer écoute (ou pas, sans erreur) ; l'ELO update fonctionne sans tracer
- QA = **protocol injection** : le runtime ne juge jamais lui-même, le caller fournit le `QAEvaluator`. Le LLM-judge n'est **jamais** le signal primaire (poids 0.3) et ne tourne jamais si un gate déterministe échoue
- Snapshot ELO matche par **agent name** (stable), pas UUID
- **Rétrocompat stricte** : tout champ V3 est optionnel/default — sans outils ni évaluateur = comportement V1/V2 identique
- **Le graphe émerge** : aucune découpe hardcodée, `divider.divide` est un appel LLM ; une sous-tâche à tag inconnu → unassigned = signal de gap roster, pas un bug
- TaskDivider / TaskAggregator **ne sont pas des Agent** (pas de claim, pas d'ELO) ; l'output d'agrégation porte le sentinel `agent_id="aggregator"`, jamais un UUID
- Triage (B2) / TaskSpecGenerator (B3) = **batch hors chemin runtime**, jamais dans `run_task` ; retournent `None` sur échec LLM, ne mutent jamais l'input
- `EvaluatorSpec` reste une **donnée** (pas du code) — c'est ce qui rend V3 (l'agent émet la spec) faisable sans réécriture

## Principes Karpathy

Réfléchir avant d'agir, simplicité d'abord, changements chirurgicaux, exécution orientée objectif → version complète dans le profil global (`~/.claude/CLAUDE.md`, chargé à chaque session). Application AAOSA : si une sub-task n'est pas dans le roadmap, la signaler avant de l'implémenter ; V1 (252 tests) est stable, ne pas la retoucher sauf bug confirmé ; chaque wave a un critère vérifiable (N tests verts, commit) formulé avant d'écrire du code.
