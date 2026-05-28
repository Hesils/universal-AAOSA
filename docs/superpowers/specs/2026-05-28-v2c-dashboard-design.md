# V2c — Dashboard d'observabilité AAOSA — Design

- **Date** : 2026-05-28
- **Statut** : validé (brainstorming), prêt pour découpe en plans
- **Projet** : universal-AAOSA
- **Prérequis** : V2b complète (471 tests), packages `tracing/`, `qa/`, `elo/` en place

## Contexte & objectif

V2c remplace le `print_timeline` console par un **dashboard web d'observabilité** du runtime AAOSA, dans l'esprit de l'aios-dashboard (Flask + cache in-memory + frontend SVG). Le dashboard donne quatre vues : santé infra du système, supervision unitaire des agents, runs de health check, et runs réels (sessions) avec un graphe de pipeline navigable.

Le point structurant découvert au cadrage : **ce n'est pas qu'un frontend**. La donnée nécessaire n'est pas encore persistée (les traces ne sont jamais flushées, le `HealthCheckReport` n'est pas sauvegardé, les system prompts ne sont nulle part sur disque). V2c = une **couche data/persistance** dans `src/aaosa/` (prérequis) + une **app dashboard** dans `dashboard/`.

## Décisions structurantes

1. **Graphe = pipeline réel uniquement**, modèle de nœud générique/extensible. Pas de nœud fantôme V3.
2. **Topologie en 3 couches spatiales** : TOP (I/O système), CENTER (logique interne), BOTTOM (agents). Le layout réserve la place pour les nœuds V3 (TaskDivider, Aggregateur, tools) sans les afficher aujourd'hui.
3. **Serveur Flask** à la aios-dashboard : `create_app(config)` factory testable, cache in-memory on-demand (pas de DB, pas de TTL), **pas de live mode** (V1 = review statique sur runs persistés).
4. **Couche data dans `src/aaosa/`** (concern runtime), **app Flask dans `dashboard/`** à la racine du repo.
5. **Tab 4 (sessions)** : graphe + stepping task-par-task + panneau todo. **Tab 3 (health check)** : sélecteur de task qui bascule le graphe d'un cas à l'autre (cas décorrélés, pas de stepping).
6. **Graphe auto-fit** : viewBox dynamique (auto-scale selon le nombre de nœuds), zéro scroll page, contrôles zoom/dézoom optionnels.
7. **Overlay au clic = modal centré style aios** (celui des messages longs du trace viewer), contenu **adapté par type de nœud**.
8. **Esthétique** : structure validée ; le skin pourra s'écarter de l'aios (décidé en implémentation).

## Hors scope (→ V3)

- TaskDivider (décomposition d'une requête user en sous-tâches ordonnées)
- Aggregateur actif (mémoire partagée interrogeable par le dispatcher, chaînage A→B)
- Tools par agent
- Live mode (WebSocket/SSE)
- Synthèse multi-outputs (l'« Integrator » est un collecteur passif des outputs de session, pas un synthétiseur)

---

## Section 1 — Couche data (`src/aaosa/`)

### Convention de store

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

### Nouveaux modèles & fonctions

| Élément | Emplacement | Rôle |
|---|---|---|
| `ExecutedEvent.llm_metadata: LLMMetadata \| None = None` | `tracing/events.py` | porte latence/tokens dans la trace (sinon Tab 1 aveugle). Optionnel avec défaut `None` → les fixtures `ExecutedEvent` existantes restent valides ; le runtime le remplit toujours |
| `AgentRegistryEntry` / `save_agent_registry(agents, path)` | `tracing/store.py` (nouveau) | persiste name, id, system_prompt, tags_with_elo |
| `SessionMeta` (session_id, started_at, ended_at, tasks[{id, description, winner_agent_id, outcome}], agent_ids) | `tracing/store.py` | métadonnée de session pour la liste + le graphe |
| `save_session(tracer, meta, runs_root)` | `tracing/store.py` | écrit `trace.jsonl` + `meta.json` |
| `save_health_check(report, test_set, directory)` | `qa/health_check.py` | mirror de `save_test_set` |

### Changements runtime

- `run_task` : émet `ExecutedEvent` enrichi de `output.llm_metadata` (l'`Output` porte déjà `LLMMetadata` : model_name, tokens_in, tokens_out, latency_ms).
- `demo/run_demo.py` et `demo/run_health_check.py` : appellent `save_session` / `save_health_check` (aujourd'hui ils `print` seulement).
- Rétrocompat : les 471 tests existants ne doivent pas casser. `ExecutedEvent.llm_metadata` est optionnel (`None` par défaut) ; seules les assertions qui inspectent l'event au runtime sont mises à jour.

*Stretch optionnel (non requis V2c) : instrumenter la latence/tokens des appels Phase 2 `claim()`.*

---

## Section 2 — Backend dashboard (`dashboard/`)

### Structure

```
dashboard/
  app.py                # create_app(config) factory
  config.py             # runs_root, host, port
  collectors/
      infra.py          # Tab 1
      agents.py         # Tab 2
      health_checks.py  # Tab 3
      sessions.py       # Tab 4
  graph_model.py        # trace -> modèle de graphe 3 couches (fonction pure)
  cache.py              # cache in-memory on-demand
  templates/ static/    # frontend
  tests/
```

### Collectors

| Collector | Tab | Source | Sortie |
|---|---|---|---|
| `InfraStats` | 1 | tous les `sessions/*/trace.jsonl` | nb sessions/runs/agents/tasks, distribution latence, tokens in/out, QA pass rate global, pass rate dans le temps |
| `Agents` | 2 | `agents/registry.json` + `elo_snapshots/*` + traces | par agent : prompt, tags+ELO courant, **historique ELO par tag** (séries horodatées), historique claim/win/success/fail |
| `HealthChecks` | 3 | `health_checks/*` | liste runs ; par run : pass rates fix_target/regression_guard, cas unstable, buckets quarantaine, TestSet (split train/test, evaluator + attribution par cas) |
| `Sessions` | 4 | `sessions/*` | liste sessions ; par session : meta + trace |

### Modèle de graphe (`graph_model.py`)

Fonction pure `build_graph(events: list[ClaimEvent], session_meta) -> GraphModel`. Groupe les events par `task_id`, dérive l'état des nœuds.

```python
GraphModel = {
  "nodes": [{ "id", "layer": "top|center|bottom",
              "type": "input|dispatch|evaluator|output|testset|agent",
              "label" }],
  "edges": [{ "from", "to" }],
  "steps": [{ "task_id", "label",
              "active_nodes": [...], "active_edges": [...],
              "winner_agent_id", "outcome",
              "detail": { per-node overlay payload } }],
}
```

- **Tab 4 (session)** : `steps` = un par task, dans l'ordre des timestamps → alimente le scrubber + le panneau todo.
- **Tab 3 (health check)** : un `GraphModel` par cas sélectionné (le sélecteur de task choisit le cas) ; pas de stepping. Le `trace.jsonl` du health check contient les N runs de chaque cas — le builder ne retient **qu'un run par cas** (le dernier) pour le graphe, et affiche le `pass_rate` agrégé du cas (ex. 4/5) en annotation.

Mapping events → état :
- `Phase1FilteredEvent` (passed, fit_score) → état agent (filtré/passé) + payload overlay Dispatch
- `Phase2ClaimedEvent` (decision, justification) → claim agent + payload overlay
- `DispatchedEvent` (agent_id, reason) → winner
- `ExecutedEvent` (output_summary, llm_metadata) → output du winner + overlay agent
- `QAEvaluatedEvent` (success, score, reason) → état Evaluator + fork pass/fail
- `EloUpdatedEvent`, `TagAcquiredEvent` → effets ELO (overlay agent)
- `UnassignedEvent` → pas de winner

### API REST (JSON)

| Endpoint | Sert |
|---|---|
| `GET /api/infra` | Tab 1 |
| `GET /api/agents` · `GET /api/agents/<id>` | Tab 2 |
| `GET /api/health-checks` · `GET /api/health-checks/<id>` · `GET /api/health-checks/<id>/graph?task_id=` | Tab 3 |
| `GET /api/sessions` · `GET /api/sessions/<id>` · `GET /api/sessions/<id>/graph` | Tab 4 |

`Cache-Control: no-store` sur les endpoints data (comme aios).

---

## Section 3 — Frontend (`templates/` + `static/`)

Vanilla JS + SVG (pas de framework), servi par Flask. Quatre tabs.

### Composant graphe (commun Tab 3 & 4)

- Rendu SVG du `GraphModel` en 3 bandes (TOP/CENTER/BOTTOM).
- **Auto-fit** : viewBox calculé selon le nombre de nœuds → tout loge sans scroll ; contrôles zoom/dézoom optionnels.
- Chemin sollicité en surbrillance ; gagnant mis en avant (pulse) ; filtrés grisés ; branche fail en pointillé.
- **Clic sur un nœud → modal centré** (style aios, appendé hors zoom), contenu adapté :
  - **Dispatch** : fit_scores Phase 1, claims + justifications Phase 2, résolution → winner
  - **Agent** : system prompt (tronqué/expandable), tags + ELO, input de la task, output (+ latence/tokens)
  - **Evaluator** : critères/gates, judge (mode + score), score final, raison
  - **Input/Output/TestSet** : task détaillée, contenu output, lien vers le cas TestSet

### Tab 1 — Infra (Grafana-like)
Cartes chiffres (sessions, runs, agents, tasks, QA pass %, tokens, latence moyenne) + charts (distribution latence, pass rate dans le temps, runs/session, tokens in/out).

### Tab 2 — Agents (supervision unitaire)
Liste agents → détail : prompt, tags+ELO courant (barres), historique ELO par tag (courbes), historique claim/win/success/fail.

### Tab 3 — Health check runs
Sélecteur de run → overview (pass rates, unstable, quarantaines) + vue TestSet (split train/test, evaluator + attribution par cas) + graphe avec **sélecteur de task** (par cas, affiche pass_rate).

### Tab 4 — Session run
Toolbar (sélecteur session + chips stats) + graphe + panneau todo (tasks de la session, cochées au fil du stepping) + scrubber (step task-par-task).

---

## Stratégie de test (TDD)

- **Couche data** : tests unitaires sur les nouveaux modèles + roundtrip JSON (save/load) ; non-régression des 471 tests.
- **`graph_model.build_graph`** : fonction pure → tests sur traces fixtures (assigned, unassigned, multi-claim, QA fail→fork TestSet, multi-task session).
- **Collectors** : tests sur un `runs_root` fixture (arborescence de fichiers) → agrégats attendus.
- **API** : tests Flask `test_client` sur `create_app(config_test)`.
- **Frontend** : hors TDD automatisé (vérif manuelle navigateur, comme aios) — la logique testable vit côté Python (collectors + graph_model).

## Découpe pressentie (détaillée dans writing-plans)

1. Couche data : events enrichis + store (registry, SessionMeta, save_session, save_health_check) + demos qui flushent
2. `graph_model.build_graph` (fonction pure)
3. Backend : create_app + cache + collectors + API
4. Frontend : composant graphe + overlay + scrubber
5. Tabs 1/2/3 + intégration finale
