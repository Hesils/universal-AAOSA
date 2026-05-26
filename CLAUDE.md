# universal-AAOSA — CLAUDE.md

Runtime multi-agents à coordination bottom-up par claiming. Le graphe d'exécution émerge des décisions distribuées des agents — il n'est pas connu à l'avance. Agnostique au domaine.

## Contexte externe

Charger si tu manques de contexte sur l'état, les décisions, ou les épiques détaillées :

- **Fiche opérationnelle** (état courant, patterns, stack) : `C:\Users\Desvignes\Documents\AIOS\context\projects\universal-AAOSA\context.md`
- **Roadmap** (épiques, sub-tasks, waves, décisions structurantes) : `C:\Users\Desvignes\Documents\AIOS\context\projects\universal-AAOSA\roadmap.md`
- **Wiki** (architecture originale, observabilité V2/V3) : `C:\Users\Desvignes\Documents\obsidian\seconde_brain\wiki\Projects\universal-AAOSA\`

Les skills `/prime` et `/save` viennent du master `.claude/` — disponibles sans configuration supplémentaire.

## État courant

**V1 complète — 252 tests verts** (commits `2fca11c` + `3ca1e0c`, 2026-05-26).

Implémenté : schemas (Task, Claim, Output, ELO), Agent (claim + execute), Phase 1 (filter + scoring), Phase 2 (collect + run_phase2 + run_phase2_async), Dispatch, Tracer (observer pattern, JSONL), Analysis (over/under-claim), Formatter (timeline console), Runner (`run_task` pipeline complet), Demo agents + fixtures + `run_demo.py` + tests E2E.

**Prochaine étape : V2** (acquisition ELO dynamique) — voir roadmap.

## Architecture

```
src/aaosa/
├── schemas/        task.py · claim.py · output.py · elo.py
├── core/           agent.py (claim + execute)
├── claiming/       scoring.py · phase1.py · phase2.py · prompts.py · dispatch.py
├── runtime/        llm_client.py · runner.py
├── tracing/        events.py · tracer.py · analysis.py · formatter.py
└── demo/           agents.py · tasks.py · run_demo.py

tests/              miroir de src/aaosa/ + conftest.py
traces/             JSONL par session (gitignored)
```

**Pipeline complet** : `Task in → filter_candidates (Phase 1) → run_phase2 (Phase 2) → dispatch → agent.execute → Output | DispatchResult`

## Stack et commandes

- Python 3.14, uv, Pydantic 2.13, OpenAI SDK 2.38.0, pytest 9.0.3, pytest-asyncio 1.3.0, python-dotenv 1.2.2
- Lancer les tests : `.venv\Scripts\python -m pytest <fichier> -v`
- Lancer la démo : `.venv\Scripts\python src\aaosa\demo\run_demo.py` (requiert `.env` avec `OPENAI_API_KEY`)
- Toujours utiliser le venv, jamais Python système

## Principes Karpathy — appliqués à AAOSA

**1. Réfléchir avant d'agir**
Si une sub-task n'est pas dans le roadmap, la signaler avant de l'implémenter. Exposer les compromis avant d'ouvrir un fichier. Nommer le flou (ambiguïté de spec, comportement indéfini) avant de choisir.

**2. Simplicité d'abord**
V1 est volontairement minimal — chaque choix dans le roadmap a écarté les abstractions prématurées. Ne pas anticiper V2/V3 sans décision explicite. Se demander : "est-ce que le roadmap dit de le faire ?"

**3. Changements chirurgicaux**
Les waves complètes (1–7, V1 entière) sont stables — ne pas retoucher sauf bug confirmé. Ne modifier que ce que la wave courante demande. Supprimer uniquement les orphelins créés par ses propres changements.

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
