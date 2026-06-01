# universal-AAOSA — CLAUDE.md

Runtime multi-agents à coordination bottom-up par claiming. Le graphe d'exécution émerge des décisions distribuées des agents — il n'est pas connu à l'avance. Agnostique au domaine.

## Contexte externe

Charger si tu manques de contexte sur l'état, les décisions, ou les épiques détaillées :

- **Fiche opérationnelle** (état courant, patterns, stack) : `C:\Users\Desvignes\Documents\AIOS\context\projects\universal-AAOSA\context.md`
- **Roadmap** (épiques, sub-tasks, waves, décisions structurantes) : `C:\Users\Desvignes\Documents\AIOS\context\projects\universal-AAOSA\roadmap.md`
- **Wiki** (architecture originale, observabilité V2/V3) : `C:\Users\Desvignes\Documents\obsidian\seconde_brain\wiki\Projects\universal-AAOSA\`
- **Design spec V2a** : `docs/superpowers/specs/2026-05-27-v2a-elo-dynamic-design.md` (dans ce repo)

Les skills `/prime` et `/save` viennent du master `.claude/` — disponibles sans configuration supplémentaire.

## État courant

**V1 complète — 252 tests** (commits `2fca11c` + `3ca1e0c`, 2026-05-26).
**V2a complète — 377 tests total** (commits `5265e3e` → `826d889`, 2026-05-27). Demo V2 validée LLM réel.
**V2b complète — 471 tests total** (commits `04f12cd` → `f4f01b3`, 2026-05-28). Demo V2b validée LLM réel (judge déclenché, ELO mis à jour), health check demo validé (4 attributions, graduate lifecycle).

**V2c complète — 588 tests total** (commits `39d46ce` → `aa356d5`, 2026-06-01). 6 épiques (01-05) + refonte graphique (06). Dashboard d'observabilité opérationnel : couche data persistée (`runs/`) + app Flask `dashboard/` (`create_app`, cache on-demand, 4 collectors, API REST) + `build_graph` pur + frontend vanilla JS/SVG (4 tabs). Contrat data validé end-to-end sur app live. **Refonte graphique « wireframe instrument » portée + validée navigateur** (`DESIGN.md`/`PRODUCT.md`, plan `v2c-06`) ; follow-ups XSS + `infra.agent_count` résorbés ; `design-lab/` supprimé. **V2c bouclée → V3.**

V2 découpée en 3 sous-parties :
- **V2a** (complète) : ELO mechanics + dual QA protocol
- **V2b** (complète) : QA complet (evaluator composable + boucle auto-amélioration)
- **V2c** (complète) : Dashboard d'observabilité (couche data `src/aaosa/` + app Flask `dashboard/`, 4 tabs)

### V3 — en cours (deep-dives → implémentation)

V3 = runtime générique par config + boucle auto-améliorante (QA générée par agents) + présentation. **14 épiques** découpées (A1-A6, B1-B7, C1-C3), détail dans `roadmap.md` (AIOS), deep-dives par épique dans `docs/superpowers/epics/v3-*.md`.

**Ordre d'implémentation (chemin critique)** : `A1 → B1 → A3 → A4 → B2 → B3 → A5 → C`. Aucune épique V3 n'est encore implémentée (toujours 588 tests). Cible après A+B : **656 tests** (A1+6, B1+10, A3+11, A4+16, B2+8, B3+7, A5+10).

- **Nature A** (généricité) : A1 agents par config · A3 subdivision de tâches (schema+threading) · A4 TaskDivider + Aggregateur (pièce centrale « le graphe émerge ») · A5 tools par agent. A2 (2e domaine) hors chemin critique.
- **Nature B** (auto-amélioration) : B1 evaluator émis par agent · B2 triage auto-attribution · B3 TaskSpecGenerator. **La nature B s'arrête à B3.**
- **Nature C** (doc/présentation) : en dernier, reflète A+B réels.

**Déferrés (2026-06-02, hors chemin critique)** : **B4 sidecar advisory + B5 canal bidirectionnel** — le `SystemAdvisory` chevauche largement l'ELO (déjà la boucle de feedback comportemental) ; B4 sans B5 = infra sans consommateur. Valeur non acquise → à réévaluer si le besoin émerge sur runs réels. Aussi hors chemin : B6 (spike ELO 3 signaux), B7 (live mode). Deep-dive `v3-b4-*.md` gardé sur disque ; **B5 n'a pas de fichier** (déferré pendant sa discussion de deep-dive). Cf. `decisions/log.md` 2026-06-02.

**Prochain pas concret** : démarrer l'implémentation **A1** (zéro dépendance, débloque le multi-domaine) ou deep-dive d'une épique non encore creusée. A1, B1, A3, A4, A5, B2, B3, B4 sont deep-divés (fichiers `v3-*.md`) ; A2, B6, B7, C restent à creuser ; B5 déferré.

## Architecture

```
src/aaosa/
├── schemas/        task.py · claim.py · output.py · elo.py
├── core/           agent.py (claim + execute)
├── claiming/       scoring.py · phase1.py · phase2.py · prompts.py · dispatch.py
├── runtime/        llm_client.py · runner.py
├── tracing/        events.py · tracer.py · analysis.py · formatter.py · store.py  # store.py = V2c (persistance)
├── demo/           agents.py · tasks.py · run_demo.py · run_health_check.py
├── elo/            formula.py · updater.py · persistence.py          # V2a (implémenté)
└── qa/             protocol.py · rule_based.py · health_check.py     # V2a (implémenté)
                    criteria.py · spec.py · judge.py · spec_evaluator.py · test_set.py · lifecycle.py · adaptive.py  # V2b (implémenté)

dashboard/          # V2c (implémenté) — app web d'observabilité
├── app.py · config.py · cache.py · graph_model.py (build_graph pur)
├── collectors/     infra.py · agents.py · health_checks.py · sessions.py
├── api/            blueprint REST (no-store, by_alias)
├── static/         js/ (graph · modal · charts · tabs/*) + css/   ·   templates/  index.html

tests/              miroir de src/aaosa/ + tests/dashboard/ + conftest.py
traces/             JSONL par session (gitignored)
elo_snapshots/      JSON snapshots ELO (gitignored)                   # V2a
test_sets/          JSON test sets (gitignored)                       # V2b
runs/               # V2c — store unifié persisté (gitignored) : agents/registry.json · elo_snapshots/
                    # · sessions/<id>/{trace.jsonl,meta.json,agents.json} · health_checks/<ts>/{report,test_set,trace,agents}
docs/superpowers/specs/  design specs · plans/  plans d'implémentation · epics/  épiques V2c
```

**Lancer le dashboard** : `.venv\Scripts\python -m dashboard` → http://localhost:5000

**Pipeline V1** : `Task in → filter_candidates → run_phase2 → dispatch → agent.execute → Output | DispatchResult`

**Pipeline V2** : `... → agent.execute → [QA evaluate] → [ELO update] → Output | QAFailure | DispatchResult`
- `evaluator=None` → V1 behavior (pas de QA, pas d'ELO update)

## Stack et commandes

- Python 3.14, uv, Pydantic 2.13, OpenAI SDK 2.38.0, pytest 9.0.3, pytest-asyncio 1.3.0, python-dotenv 1.2.2
- Lancer les tests : `.venv\Scripts\python -m pytest <fichier> -v`
- Lancer la démo : `.venv\Scripts\python src\aaosa\demo\run_demo.py` (requiert `.env` avec `OPENAI_API_KEY`)
- Toujours utiliser le venv, jamais Python système
- Toujours utiliser la derniere version stable possible d'un package

## Principes Karpathy — appliqués à AAOSA

**1. Réfléchir avant d'agir**
Si une sub-task n'est pas dans le roadmap, la signaler avant de l'implémenter. Exposer les compromis avant d'ouvrir un fichier. Nommer le flou (ambiguïté de spec, comportement indéfini) avant de choisir.

**2. Simplicité d'abord**
Chaque version est volontairement minimale — chaque choix dans le roadmap a écarté les abstractions prématurées. Ne pas anticiper V2b/V2c/V3 sans décision explicite. Se demander : "est-ce que la spec V2a dit de le faire ?"

**3. Changements chirurgicaux**
V1 (252 tests) est stable — ne pas retoucher sauf bug confirmé. V2a doit maintenir la backward compat (`evaluator=None` = V1 behavior). Ne modifier que ce que la wave courante demande. Supprimer uniquement les orphelins créés par ses propres changements.

**4. Exécution orientée objectif**
Chaque wave a un critère vérifiable : N tests verts, commit. Formuler le critère avant d'écrire du code. Pour les tâches multi-fichiers, plan bref (quels fichiers, dans quel ordre) avant d'agir.

## Patterns établis

- **Imports** : absolus uniquement — `from aaosa.schemas.task import Task`, jamais relatifs
- **Timestamp UTC** : `Field(default_factory=lambda: datetime.now(timezone.utc))` — jamais `datetime.utcnow()` (deprecated Python 3.14)
- **Validator non-empty** : `@field_validator` + `@classmethod`
- **Invariant cross-fields** : `@model_validator(mode="after")` retourne `self`
- **Héritage ConfigDict** : Pydantic v2 hérite `model_config` des parents — ne pas re-déclarer sauf override intentionnel
- **`extra="forbid"`** : hérité via `_BaseEvent` — ne pas surcharger dans les classes enfants
- **`agent_id`/`task_id`** : toujours setter depuis `self.id`/`task.id` dans `claim()`, jamais depuis la réponse LLM
- **Import circulaire** `agent.py ↔ prompts.py` : résolu par import local de `prompt_template` dans `claim()`
- **TDD subagent-driven** : tests écrits avant l'impl, subagents séparés test-writers / code-writers / reviewer

## Séparations strictes à ne pas briser

- `fit_score` n'est **pas** injecté dans le prompt Phase 2 — l'agent raisonne sans son score système
- `passes_filter` et `fit_score` sont des **fonctions pures** sur (Agent, Task), pas des méthodes d'Agent
- Phase 1 = déterministe sans LLM / Phase 2 = cognitif avec LLM — ne jamais mélanger
- Tracer = **pattern observer** découplé — le runtime émet, le tracer écoute (ou pas, sans erreur)
- QA = **protocol injection** — le runtime ne juge jamais lui-même, le caller fournit le `QAEvaluator`
- ELO update fonctionne **sans tracer** — le tracer reçoit les events ELO mais n'est pas requis
- Snapshot matche par **agent name** (stable), pas UUID (régénéré à chaque instanciation)

## Design V2a — Résumé rapide

Spec complète : `docs/superpowers/specs/2026-05-27-v2a-elo-dynamic-design.md`

- **Formule ELO** : succès `K*(req/agent)`, échec `-K*(agent/req)`, per-tag, K=5, clamp ±10, floor=1, ceiling=95
- **Dual QA** : runtime (inline `run_task`, gate qualité + ELO immédiat) + health check (batch, vérification système)
- **QAEvaluator Protocol** : structural typing, `evaluate(task, output) → QAResult`
- **`run_task` V2** : `evaluator: QAEvaluator | None = None` — None = V1 compat
- **Return type V2** : `Output | DispatchResult | QAFailure`
- **Tag acquisition** : succès + tag absent → ajout au level requis, puis update normal
- **Persistence** : in-memory + snapshot JSON (`save_snapshot`, `load_snapshot`, `apply_snapshot`)

## Design V2b — Résumé rapide

Spec complète : `docs/superpowers/specs/2026-05-28-v2b-qa-complet-design.md`. Plans : `docs/superpowers/plans/v2b-01..09.md`.

- **Evaluator-as-spec** : `EvaluatorSpec` Pydantic déclaratif (sérialisable JSON → pont V3). Interprété par `SpecEvaluator` (satisfait `QAEvaluator` Protocol). Critères = fonctions dans un registry, retournant `CriterionOutcome` granulaire.
- **Hybride** : gates déterministes (rejet gratuit, judge sauté si échec) + critères scorés + LLM-judge pondéré. `final = (1-w)*det + w*judge.overall`, `success = final >= success_threshold`.
- **LLM-judge** : 2 modes (`rubric` runtime / `reference_based` health check). Jamais signal primaire, poids 0.3, température 0. Référence portée par construction du `SpecEvaluator`, pas par le Protocol.
- **Boucle fermée** : échec runtime → `failure_to_test_case` → `TestSet` (persisté `test_sets/`) → `run_health_check` de régression.
- **Lifecycle** : `fix_target` → `regression_guard` via `graduate` (par taux). `active_cases` filtre regression_guard + fix_target attribués `agent`.
- **Health check N runs** : `run_health_check(..., n_runs=5)`, taux par cas, flag `unstable` (0.4-0.6). Read-only ELO (mode V1).
- **Attribution** : champ sur `TestCase` (`agent`/`task_spec`/`evaluator`/`unattributed`), quarantaine `task_spec`.
- **Stretch** : `build_adaptive_spec(task) -> EvaluatorSpec` déterministe — seam V3.

### Séparations strictes V2b à ne pas briser

- L'evaluator est une **donnée** (`EvaluatorSpec`), pas du code — c'est ce qui rend V3 (agent émet la spec) faisable sans réécriture
- Le LLM-judge n'est **jamais** le signal primaire — les gates déterministes portent le poids
- Le judge ne tourne **jamais** si un gate échoue (coût maîtrisé)
- Health check **read-only sur l'ELO** (mode V1, comme V2a) — pas de mutation
- Un échec n'est `regression_guard` que **quand il est corrigé** — jamais avant
- `TestCase`/`TestSet` portent `__test__ = False` (sinon collecte pytest)

## Design V2c — Résumé rapide

Spec complète : `docs/superpowers/specs/2026-05-28-v2c-dashboard-design.md`. Épiques : `docs/superpowers/epics/v2c-01..05.md`. Plans : `docs/superpowers/plans/v2c-02..06.md`. **Complète + validée navigateur (2026-06-01, 588 tests).**

Dashboard web d'observabilité remplaçant `print_timeline`. Constat : la donnée n'est pas persistée → V2c = couche data (`src/aaosa/`) + app Flask (`dashboard/`).

- **Couche data** (Épique 01, prérequis) : `ExecutedEvent.llm_metadata: LLMMetadata | None = None` (optionnel → rétrocompat 471 tests), `store.py` (`AgentRegistryEntry`/`save_agent_registry`, `SessionMeta`, `save_session`), `save_health_check`, demos qui flushent dans `runs_root/`.
- **`graph_model.build_graph`** (Épique 02, fonction pure) : `list[ClaimEvent] + session_meta -> GraphModel` (nodes/edges/steps, 3 couches TOP/CENTER/BOTTOM). Tab 4 = un step/task ordonné ; Tab 3 = un run/cas + pass_rate agrégé.
- **Backend Flask** (Épiques 03a/03b) : `create_app(config)` factory, cache in-memory on-demand, 4 collectors (infra/agents/health_checks/sessions), API REST (`Cache-Control: no-store`).
- **Frontend** (Épiques 04/05) : vanilla JS + SVG, composant graphe auto-fit + overlay modal par type de nœud + scrubber, 4 tabs.
- **Refonte graphique** (Épique 06) : direction **« wireframe instrument »** (dark, neutres graphite, hero ember/fire) — système verrouillé dans `DESIGN.md` + `PRODUCT.md` (racine), plan `v2c-06`. CSS + markup JS only (backend/`build_graph` intouchés). Graphe hex tree-tiers (agents en haut, I/O en bas) inversé dans `graph.js`, pulses ember sur le chemin actif, scale-field + onde diagonale, stat strip, charts gridlines. Follow-ups XSS (`util.js esc()`) + `infra.agent_count` (compte par nom) résorbés.

### Séparations strictes V2c à ne pas briser

- `ExecutedEvent.llm_metadata` reste **optionnel** (`None` par défaut) — ne pas casser les fixtures `ExecutedEvent` existantes
- Couche data dans `src/aaosa/` (concern runtime), app Flask dans `dashboard/` (racine) — ne pas mélanger
- `build_graph` = **fonction pure** sans effet de bord (cœur testable, frontend hors TDD auto)
- Graphe = **pipeline réel uniquement** — aucun nœud V3 (TaskDivider, Aggregateur, tools) produit
- **Pas de live mode** en V1 (review statique sur runs persistés)
