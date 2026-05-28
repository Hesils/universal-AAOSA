# V2c — Épique 1 — Couche data & persistance

- **Couche** : `src/aaosa/` (runtime / data)
- **Statut** : à creuser (deep-dive → plan → impl)
- **Dépendances** : aucune. **Prérequis bloquant de toute la V2c.**
- **Spec source** : `docs/superpowers/specs/2026-05-28-v2c-dashboard-design.md` — Section 1.

## Contexte

V2c est un dashboard web d'observabilité du runtime AAOSA. Le constat structurant du cadrage : **ce n'est pas qu'un frontend**. La donnée nécessaire n'est pas persistée aujourd'hui — les traces ne sont jamais flushées, le `HealthCheckReport` n'est pas sauvegardé, les system prompts ne vivent nulle part sur disque. Cette épique construit la couche data qui rend tout le reste possible.

## Décisions portées

- **#4** — La couche data vit dans `src/aaosa/` (concern runtime), l'app Flask dans `dashboard/` à la racine. Cette épique ne touche que `src/aaosa/` et `demo/`.
- **Contrainte rétrocompat** — les 471 tests existants ne doivent pas casser. `ExecutedEvent.llm_metadata` est optionnel (`None` par défaut) → les fixtures `ExecutedEvent` existantes restent valides ; le runtime le remplit toujours. Seules les assertions qui inspectent l'event au runtime sont mises à jour.

## Convention de store

Racine configurable `runs_root/` (défaut : `runs/` à la racine du repo) :

```
runs_root/
  agents/registry.json                 # NOUVEAU
  elo_snapshots/<ts>.json + latest.json # existe déjà
  sessions/<session_id>/
      trace.jsonl                       # flush du Tracer (existe, jamais appelé)
      meta.json                         # NOUVEAU (SessionMeta)
  health_checks/<ts>/
      report.json                       # NOUVEAU (HealthCheckReport persisté)
      test_set.json                     # snapshot du TestSet utilisé
      trace.jsonl                       # trace du run health check
```

## Nouveaux modèles & fonctions

| Élément | Emplacement | Rôle |
|---|---|---|
| `ExecutedEvent.llm_metadata: LLMMetadata \| None = None` | `tracing/events.py` | porte latence/tokens dans la trace (sinon Tab 1 aveugle). Optionnel avec défaut `None` |
| `AgentRegistryEntry` / `save_agent_registry(agents, path)` | `tracing/store.py` (nouveau) | persiste name, id, system_prompt, tags_with_elo |
| `SessionMeta` (session_id, started_at, ended_at, tasks[{id, description, winner_agent_id, outcome}], agent_ids) | `tracing/store.py` | métadonnée de session pour la liste + le graphe |
| `save_session(tracer, meta, runs_root)` | `tracing/store.py` | écrit `trace.jsonl` + `meta.json` |
| `save_health_check(report, test_set, directory)` | `qa/health_check.py` | mirror de `save_test_set` |

## Changements runtime

- `run_task` : émet `ExecutedEvent` enrichi de `output.llm_metadata` (l'`Output` porte déjà `LLMMetadata` : model_name, tokens_in, tokens_out, latency_ms).
- `demo/run_demo.py` et `demo/run_health_check.py` : appellent `save_session` / `save_health_check` (aujourd'hui ils `print` seulement).

*Stretch optionnel (non requis V2c) : instrumenter la latence/tokens des appels Phase 2 `claim()`.*

## Stratégie de test (TDD)

- Tests unitaires sur les nouveaux modèles + roundtrip JSON (save/load) pour `AgentRegistryEntry`, `SessionMeta`, `save_session`, `save_health_check`.
- Non-régression : les 471 tests existants passent toujours (vérifier en particulier les fixtures `ExecutedEvent`).

## Critères de done

- [ ] `ExecutedEvent.llm_metadata` optionnel, fixtures existantes intactes.
- [ ] `store.py` créé avec registry + `SessionMeta` + `save_session`, roundtrip JSON testé.
- [ ] `save_health_check` écrit report + test_set + trace dans `health_checks/<ts>/`.
- [ ] Les deux demos flushent réellement sur disque (`runs_root/`).
- [ ] Suite complète verte (471 + nouveaux tests).

## À creuser en session de deep-dive

- Forme exacte de `LLMMetadata` déjà portée par `Output` (vérifier le modèle existant avant d'ajouter).
- Génération du `session_id` et des timestamps `started_at/ended_at` (qui les pose, où).
- Format `trace.jsonl` actuel produit par le `Tracer` (le flush existe mais n'est jamais appelé — confirmer la signature).
- Schéma `tags_with_elo` dans le registry vs source ELO (`elo_snapshots/latest.json`).
