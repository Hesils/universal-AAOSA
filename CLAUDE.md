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

**V1 complète — 252 tests verts** (commits `2fca11c` + `3ca1e0c`, 2026-05-26).

**V2a design spec validée** (commit `bd5078e`, 2026-05-27). Prochaine étape : plan d'implémentation V2a.

V2 découpée en 3 sous-parties :
- **V2a** (spec validée) : ELO mechanics + dual QA protocol
- **V2b** (scaffoldé) : QA complet (test sets, injection échecs, train/test split)
- **V2c** (scaffoldé) : Trace viewer complet (HTML/JS, stats)

## Architecture

```
src/aaosa/
├── schemas/        task.py · claim.py · output.py · elo.py
├── core/           agent.py (claim + execute)
├── claiming/       scoring.py · phase1.py · phase2.py · prompts.py · dispatch.py
├── runtime/        llm_client.py · runner.py
├── tracing/        events.py · tracer.py · analysis.py · formatter.py
├── demo/           agents.py · tasks.py · run_demo.py
├── elo/            formula.py · updater.py · persistence.py          # V2a (non implémenté)
└── qa/             protocol.py · rule_based.py · health_check.py     # V2a (non implémenté)

tests/              miroir de src/aaosa/ + conftest.py
traces/             JSONL par session (gitignored)
elo_snapshots/      JSON snapshots ELO (gitignored)                   # V2a
docs/superpowers/specs/  design specs
```

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
