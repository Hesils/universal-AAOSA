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

**V3 — chemin critique A+B complet — 669 tests total** (commits `68cf426` → `4bd52d9`, 2026-06-02). A1, B1, A3, A4, B2, B3, A5 implémentés en TDD. Nature A (généricité) et nature B (auto-amélioration) terminées.

**V3 — observabilité end-to-end vague 1 — 690 tests total** (commits `5f55420` → `6c5c2bf`, 2026-06-02). Pipeline + events câblés pour démontrer le chemin critique end-to-end avec LLM réel : dette B1 résorbée, `AdaptiveSpecEvaluator` (spec LLM paresseuse par tâche), events enrichis (`QAResult.spec_used`, `QAEvaluatedEvent.spec`, `TaskDividedEvent.sub_tasks`), runner propage le tracer à `execute`, toolbox stubbée + 2 scripts démo (`run_demo_v3`, `run_health_check_v3`). **Validé LLM réel** : run divisé → 6 sous-tâches, 16 tool calls, 6 QA avec spec, 1 agrégation, persisté. Reste **C** (doc/présentation, non démarrée).

**V3 — observabilité vague 2 (frontend) — 699 tests total** (commits `9e8cfdc` → `05ee7a4`, 2026-06-02, branche `feat/v3-observabilite-vague2-frontend`). Réécriture de `build_graph` du modèle « un step = une tâche » vers « un step = un jalon » (`input/divider/dispatch/agent/tool/evaluator/aggregator/output`) : graphe cumulatif rejouant un run unique (divisé ou simple), 4e tier `tools` (canopée, RLE par nom de tool), TODO vivante par jalon, modals divider/aggregator/tool + spec evaluator. `GraphStep` porte `milestone_type`/`sub_task_id`/`order_index`/`active_nodes`/`active_edges`/`todo` ; arêtes backbone cumulatives, fan-out transitoires (`_EdgeAccumulator`). Backend TDD (Partie A, tasks 1-8, subagent-driven + review qualité) ; frontend validé contrat API live (Partie B, tasks 9-12, `graph.js`/`modal.js`/`sessions.js`/CSS). **Validation navigateur (Task 13) FAITE** (2026-06-03 : checklist Sessions OK + non-régression health tab OK, sign-off Quentin). **Limitation assumée** : une session multi-tâches indépendantes ne rend que son run primaire (1 run/graphe, décidé avec Quentin). Reste **C** (doc/présentation).

**V3 — D2 agrégateur DAG-aware — 761 tests total** (2026-06-05, branche `feat/v3-d2`). `run_chain` renvoie `dict[str, Output]` ; `_sinks` pur calcule les sinks du sous-DAG ; `run_with_recovery` court-circuite à 1 sink (0 appel LLM, 0 `TaskAggregatedEvent`) et agrège sur les sinks à ≥2 ; `build_graph` ne montre l'`aggregator` que sur `TaskAggregatedEvent` réel, `_graph_sinks` duplique la règle côté dashboard. Prompt agrégateur resserré (« résultats complémentaires »).

**V3 — D4 refonte génération évaluateur — 822 tests total** (2026-06-05, branche `master`). Moteur B : schéma LLM-facing `type`-discriminé (`_LLMCriterion` avec `type`/`importance`/`rationale`), caps déterministes (≤4 `llm_check`, ≤6 scorés), threshold dérivé du max ELO requis (0.8/0.7/0.6), `CriterionSpec.rationale` additif, clés distinctes `name#k` dans `criteria_results`. Moteur A : `build_llm_spec(failure_context=...)` + `AdaptiveSpecEvaluator(failure_context=...)` + route `evaluator` D3 construit et passe un `FailureContext` (spec régénérée informée par l'échec précédent, critères ratés, diagnostic). Route `evaluator` D3 débloquée (était un no-op à temp=0, specs identiques). Reste **C** (doc/présentation) et **Task 9 D4** (spike union discriminée stricte, optionnel).

**V3 — finitions observabilité (3 TODOs) — 710 tests total** (2026-06-03, mergé sur master). Les 3 TODOs résiduels post-vague 2 sont résorbés :
1. **Modal Evaluator affiche l'output évalué** (`4146797`) : `renderEvaluator` (`dashboard/static/js/modal.js`) rend « Output évalué » = `step.detail.agents[winner].output_content` (fallback `step.detail.output.output_content`), run divisé et simple. Validé navigateur.
2. **Seed health check B3 — caveat vague 1 résorbé** (branche `feat/v3-seed-tuning-health-check`, `a382f98`+`fe2e10e`, merge `7f40a55`) : seed `run_health_check_v3` réécrit en 3 cas conçus pour orienter le triage B2 vers `agent`/`task_spec`/`evaluator` distincts → B3 fire end-to-end au run réel. Clé : pour qu'une attribution ne retombe pas sur `agent`, l'output ne doit pas être imputable à l'agent (cas `task_spec` = contraintes contradictoires + output de bonne foi pointant l'infaisabilité ; cas `evaluator` = bon output + gate `min_length` inadapté). Spec/plan : `docs/superpowers/{specs,plans}/2026-06-03-v3-seed-tuning-health-check*`.
3. **Seed `run_demo_v3` passe le QA réel** (commits `3946eec`→`4f0b178`, merge `1dc8262`) : le run `unassigned` venait de DEUX causes. (a) **Invariants V2b verrouillés par construction** dans `src/aaosa/qa/adaptive.py` — retrait des champs `weight` (`_LLMJudge`) et `gate` (`_LLMCriterion`) des schémas LLM-facing (`extra="forbid"`) → judge toujours 0.3, seul `non_empty` gate via `_ensure_non_empty_gate` (`build_llm_spec` ne pouvait plus émettre un judge à poids 1.0 ni `min_length` en gate). (b) **Qualité réelle** — prompts agents orientés investigation-via-tools + réponse complète, `explain_query_plan` suggère des index concrets. Résultat : 3 runs réels → `divided`, 6/6 sous-tâches passent le QA (0.897-1.0), agrégation des 6 outputs. **Insight transférable** : un bug de génération de spec peut se déguiser en « agents pas assez bons » — capturer les `reason` QA réelles avant de tuner. Spec/plan : `docs/superpowers/{specs,plans}/2026-06-03-v3-seed-tuning-run-demo*`.

**V3 — démo phase 1 : observabilité série D — 883 tests total** (2026-06-06, worktree `feat+v3-demo-phase1-observabilite` mergé sur master, plan `docs/superpowers/plans/2026-06-06-v3-demo-phase1-observabilite-serie-d.md`, 17 tasks). Backend TDD subagent-driven (Tasks 1-11) : `DiagnosedEvent` (émis par `_route_diagnostic`, y compris unattributed) + 2e `QAEvaluatedEvent` à la ré-éval D3 ; `build_graph` réécrit en **arbre émergent namespacé** (partition `task_id` + passes retry, `_build_tree` récursif avec fallback racine, walk unique — run simple = arbre dégénéré, chaîne D3 par inférence, `roster_gap` nœud terminal, TAGGER inféré, TODO hiérarchique `parent_id`/`depth`/`first_step_index`). Frontend sous `/impeccable` (Tasks 12-17) : `graph.js` arbre bottom-up delta 45° (k-rows, **tronc centré** — silhouette arbre, pas de bloc), `camera.js` (zoom ancré curseur, pan, **follow par branche**), **révélation par sous-arbre** (un divider appelé révèle sa paire DIVIDER/AGGREGATOR + les arches enfants ; un enfant divisé ne montre que son dispatch jusqu'à SON divider ; DIAG/GAP événementiels, nés à leur jalon), colorway crest→fire, modals DIAG/GAP/TAGGER + origine divider, scrubber enrichi (uuid → nom d'agent). **Sign-off Quentin 2026-06-06** : réserve arbre pur (spec §8) tranchée en faveur de l'arbre pur, retrait du nœud `testset` confirmé, non-régression Health OK. Sessions de validation : synthétique D3+gap, synthétique profondeur 2 (récursion D1), divisé réel, simple réel. **Prochaine étape démo : phases 2-5** (tools YAML → monde simulé + roster → CLI `run`/`campaign` → campagne + curation), puis live mode (ex-B7) et nature C.

V2 découpée en 3 sous-parties :
- **V2a** (complète) : ELO mechanics + dual QA protocol
- **V2b** (complète) : QA complet (evaluator composable + boucle auto-amélioration)
- **V2c** (complète) : Dashboard d'observabilité (couche data `src/aaosa/` + app Flask `dashboard/`, 4 tabs)

### V3 — chemin critique A+B implémenté (669 tests)

V3 = runtime générique par config + boucle auto-améliorante (QA générée par agents) + présentation. **14 épiques** découpées (A1-A6, B1-B7, C1-C3), détail dans `roadmap.md` (AIOS), deep-dives par épique dans `docs/superpowers/epics/v3-*.md`.

**Chemin critique `A1 → B1 → A3 → A4 → B2 → B3 → A5` : tous implémentés** (commits `68cf426` → `4bd52d9`). **669 tests** (588 V2c + 81 V3). Reste **C**.

- **Nature A** (généricité) — chemin critique complet : A1 agents par config YAML (`config/loader.py`, `demo/agents.yaml`) ✓ · A3 subdivision (`Task` +4 champs, `run_chain` tri Kahn) ✓ · A4 TaskDivider + Aggregateur (« le graphe émerge », `runtime/divider.py`+`aggregator.py`, `run_divided_task`) ✓ · A5 tools par agent (`core/tool.py`, boucle tool-use dans `execute`) ✓. **A2 (2e domaine) hors chemin critique, non fait.**
- **Nature B** (auto-amélioration) — **terminée** : B1 evaluator émis par LLM (`llm_check`, `build_llm_spec`) ✓ · B2 triage auto-attribution (`qa/triage.py`) ✓ · B3 TaskSpecGenerator (`qa/task_spec_generator.py`) ✓. Boucle complète : échec → triage → correction tâche → re-triage → health check (orchestration côté caller).
- **Nature C** (doc/présentation) : en dernier, reflète A+B réels. **Non démarrée, pas encore deep-divée.**

**Dette B1 — RÉSORBÉE** (vague 1, `ad959f3`) : `SpecEvaluator.__init__` exige désormais un client si un `judge` **ou** un `llm_check` est présent, et `evaluate` injecte `self.client` dans les params des critères (`{**c.params, "client": self.client}`) aux deux sites d'appel. `QAResult.spec_used` est renseigné. Une spec contenant `llm_check` tourne en runtime réel. `AdaptiveSpecEvaluator(client)` génère la spec via `build_llm_spec` dans `evaluate` (zéro changement de signature runner).

**Caveat vague 1 — RÉSORBÉ (2026-06-03)** : le triage (B2) classait les 3 cas seedés en `agent` → B3 tournait à vide. Seed `run_health_check_v3` réécrit (cf. finitions observabilité, TODO 2) → B3 fire end-to-end au run réel.

**Déferrés (2026-06-02, hors chemin critique)** : **B4 sidecar advisory + B5 canal bidirectionnel** — le `SystemAdvisory` chevauche largement l'ELO (déjà la boucle de feedback comportemental) ; B4 sans B5 = infra sans consommateur. Valeur non acquise → à réévaluer si le besoin émerge sur runs réels. Aussi hors chemin : B6 (spike ELO 3 signaux), B7 (live mode). Deep-dive `v3-b4-*.md` gardé sur disque ; **B5 n'a pas de fichier**. Cf. `decisions/log.md` 2026-06-02.

**Prochain pas concret** : deep-dive **C** (doc/présentation) — trancher l'audience (recruteur / technique) et quoi montrer en priorité (claiming émergent ? boucle auto-améliorante ? dashboard ?). A2 (2e domaine) reste disponible comme matériel pour C.

## Architecture

```
src/aaosa/
├── schemas/        task.py (+4 champs V3-A3) · claim.py · output.py (+tool_calls_count V3-A5) · elo.py
├── core/           agent.py (claim + execute avec boucle tool-use V3-A5) · tool.py (MAX_TOOL_ROUNDS=20)  # tool.py = V3-A5
├── claiming/       scoring.py · phase1.py · phase2.py · prompts.py · dispatch.py (+dependency_failed A3, +execution_failed vague1)
├── config/         loader.py  # V3-A1 (load_agents YAML)
├── runtime/        llm_client.py · runner.py (+run_chain V3-A3, +run_divided_task V3-A4, containment vague1) · divider.py (hérite tags parent vague1) · aggregator.py  # divider/aggregator = V3-A4
├── tracing/        events.py (+ToolCalled/TaskDivided/TaskAggregated V3, +DividedSubTask & QAEvaluatedEvent.spec vague1) · tracer.py · analysis.py · formatter.py · store.py  # store.py = V2c
├── demo/           agents.py (loader A1) · agents.yaml · tasks.py · run_demo.py (+run divisé A4) · run_health_check.py · tools.py (toolbox stubbée vague1) · run_demo_v3.py · run_health_check_v3.py  # *_v3 = vague1
├── elo/            formula.py · updater.py · persistence.py          # V2a (implémenté)
└── qa/             protocol.py (+QAResult.spec_used vague1) · rule_based.py · health_check.py     # V2a (implémenté)
                    criteria.py (+llm_check V3-B1) · spec.py · judge.py · spec_evaluator.py (+AdaptiveSpecEvaluator & inject client vague1) · test_set.py · lifecycle.py · adaptive.py (+build_llm_spec V3-B1)  # V2b
                    triage.py · task_spec_generator.py  # V3-B2 / V3-B3

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

**Pipeline V3 (chaîne A3)** : `run_chain([sub_tasks]) → tri topologique Kahn → run_task par tâche, required_outputs injectés depuis les deps réussies`. **Containment (vague1)** : une exception de `run_task` (ex: `MAX_TOOL_ROUNDS`) est attrapée → `DispatchResult(status="execution_failed")`, la chaîne continue, les sous-tâches réussies restent agrégeables.
**Pipeline V3 (graphe émergent A4)** : `run_divided_task → divider.divide (LLM) → run_chain → aggregator.aggregate (LLM) | fallback successful[-1] | DispatchResult(unassigned)`
**Démo end-to-end V3 (vague1)** : `run_demo_v3.py` (incident divisé + tools + `AdaptiveSpecEvaluator`) · `run_health_check_v3.py` (seed unattributed → triage B2 → fix B3 → re-triage → `run_health_check`). Lancer : `.venv\Scripts\python src\aaosa\demo\run_demo_v3.py` (requiert `OPENAI_API_KEY`).
**Boucle auto-amélioration V3 (B1-B3)** : `échec runtime → failure_to_test_case → triage_unattributed (B2) → fix_task_spec_cases (B3) → triage (B2) → active_cases → run_health_check` (orchestration côté caller)

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
- Graphe = **pipeline réel uniquement** — les nœuds `divider`/`aggregator` (A4) émergent d'un `TaskDividedEvent` réel dans la trace, jamais spéculatifs
- **Pas de live mode** en V1 (review statique sur runs persistés)

### Séparations strictes V3 à ne pas briser

- **Rétrocompat stricte** : tout champ V3 est optionnel/default — `Task` +4 champs (A3), `Agent.tools=[]` (A5), `LLMMetadata.tool_calls_count=0` (A5). `run_task`/`run_chain`/`claim`/`execute` sans outils = comportement V1/V2 identique
- TaskDivider et TaskAggregator (A4) **ne sont pas des Agent** — pas de `claim`, pas de `tags_with_elo`. L'output de l'aggregateur porte le sentinel `agent_id="aggregator"`, jamais un UUID
- **Le graphe émerge** : aucune découpe hardcodée — `divider.divide` est un appel LLM. Une sous-tâche avec un tag inconnu → unassigned = signal de gap roster, pas un bug
- Triage (B2) et TaskSpecGenerator (B3) = **batch, hors chemin runtime** — jamais appelés dans `run_task`. `triage_case`/`fix_task_spec` retournent `None` sur échec LLM (jamais d'exception propagée), ne mutent jamais l'input (nouveau `TestSet`)
- B3 reset l'attribution à `"unattributed"` (repasse par B2), conserve `task.id`/`role`/`wrong_output`. Orchestration B2↔B3 **côté caller**, zéro couplage entre modules
- `EvaluatorSpec` reste une **donnée** (B1 ne change que le producteur : `build_adaptive_spec` déterministe → `build_llm_spec` LLM, format inchangé). `llm_check` préservé par `_filter_unknown_criteria`. **`AdaptiveSpecEvaluator` (vague1)** satisfait le Protocol `QAEvaluator` et génère la spec dans `evaluate` — le runtime injecte un évaluateur, ne génère jamais la spec lui-même (séparation V2b préservée). **Invariants V2b verrouillés par construction (2026-06-03)** : les schémas LLM-facing de `adaptive.py` n'exposent plus `weight` (`_LLMJudge`) ni `gate` (`_LLMCriterion`) → `build_llm_spec` ne peut pas émettre un judge à poids ≠ 0.3 ni mettre un critère scoré en gate ; seul `non_empty` reste gate via `_ensure_non_empty_gate`. Le LLM choisit les critères, pas leur pondération
- Boucle tool-use (A5) : tout `finish_reason != "tool_calls"` est terminal · cap `MAX_TOOL_ROUNDS=20` (relevé de 10 en vague1 pour laisser gpt-4o-mini converger) → `RuntimeError`, **contenu par `run_chain`** (jamais propagé jusqu'à tuer un run divisé) · `ToolCalledEvent` émis seulement si `tracer` fourni · `run_task` propage le `tracer` à `execute` (vague1, sinon les tool calls runtime restaient invisibles)
- **`SpecEvaluator` (vague1)** : le client est requis dès qu'un `judge` **ou** un `llm_check` est présent (garde constructeur), injecté dans les params des critères à l'évaluation. `QAResult.spec_used` porte la spec utilisée → recopiée sur `QAEvaluatedEvent.spec`
- **Agrégation par sinks (D2)** : à un fan-in, `run_chain` renvoie `dict[str, Output]` (réussis par id, ordre topologique) ; le helper pur `_sinks(sub_tasks, outputs_by_id)` calcule les sinks (un réussi non consommé par un réussi). `run_with_recovery` branche : 0 réussi → `unassigned` · **1 sink → court-circuit** (renvoie l'`Output` du sink tel quel, garde son `agent_id` réel, aucun appel LLM, aucun `TaskAggregatedEvent`) · ≥2 sinks → `aggregator.aggregate(task, sinks, ...)`, fallback `sinks[-1]` sur exception. Le sentinel `agent_id="aggregator"` reste réservé à l'agrégateur réel. Côté dashboard, `build_graph` ne montre l'`aggregator` que sur un `TaskAggregatedEvent` réel ; au court-circuit il rend un OUTPUT terminal depuis le sink ; `total`/`collected` comptent les sinks (règle de sink dupliquée runtime + `_graph_sinks`, duplication assumée vs couplage data).
