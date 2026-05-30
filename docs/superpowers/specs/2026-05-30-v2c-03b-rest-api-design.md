# V2c — Épique 03b — API REST + addendum data B1 — Design

- **Date** : 2026-05-30
- **Statut** : validé (deep-dive cross-check), prêt pour writing-plans
- **Projet** : universal-AAOSA
- **Prérequis** : Épique 03a complète (557 tests : collectors + cache + factory `create_app`), Épique 02 (`build_graph` pur)
- **Spec source** : `2026-05-28-v2c-dashboard-design.md` Section 2 — API REST

## Contexte & objectif

Deuxième moitié du backend dashboard : la couche HTTP qui expose les 4 collectors (03a) et `build_graph` (02) en JSON. C'est le contrat consommé par le frontend (Épiques 04 graphe, 05 tabs). Testée via `test_client` Flask sur `create_app(config_test)` pointant un `runs_root` fixture.

**Résultat du cross-check aval (04/05)** : comme pour 03a, **aucun gap de données**. Les collectors 03a + `build_graph` couvrent tout ce que le frontend lit. 03b est une couche de **transport et de forme**, sauf un point de **robustesse data** (S5 ci-dessous) qui justifie un petit addendum additif à la couche data.

## Décisions du deep-dive (2026-05-30)

- **S1 — Sérialisation** : helper unique `json_response(model)` = `jsonify(model.model_dump(by_alias=True, mode="json"))` + header `Cache-Control: no-store`. `by_alias=True` produit `from`/`to` pour les `GraphEdge` (alias `from`) ; `mode="json"` convertit `datetime`→ISO et `Path`→str. Tous les endpoints data passent par ce helper.
- **S2 — Blueprint** : un seul `Blueprint("api", url_prefix="/api")` enregistré dans `create_app`. Routes minces lisant `runs_root` (config) et le cache depuis `app.config` (attachés en 03a).
- **S3 — Contrat session (Option A)** : `GET /api/sessions/<id>` renvoie **meta seule** (+ agents du run, voir B1), `GET /api/sessions/<id>/graph` renvoie le `GraphModel` **nu**. Symétrie avec `/api/health-checks/<id>/graph` : le composant graphe (commun Tab 3 & 4, Épique 04) a un contrat uniforme `.../graph -> GraphModel`.
- **S4 — Graphe HC sans `task_id` (Option B)** : `GET /api/health-checks/<id>/graph` sans `task_id` → renvoie le graphe du **premier cas graphable** (l'onglet charge sans flash d'erreur ; le front passe ensuite un `task_id` explicite). Aucun cas graphable ou run absent → 404.
- **S5 / B1 — Identité agent par run (snapshot)** : voir Section « Addendum data ». L'`agent_id` est régénéré à chaque instanciation (les snapshots ELO matchent par nom, pas UUID) ; un `runs_root` multi-run rendrait un join overlay `agent_id`→registry global périmé (404). B1 fige l'identité des agents **au moment du run**.
- **S6 — Erreur 404** : corps JSON cohérent `{"error": "<message>"}` + `no-store`, jamais un 404 nu. Le front a une forme d'erreur unique.

## Hors scope

Frontend (Épiques 04/05), live mode (WebSocket/SSE), tout nouveau type de nœud V3. Pas de pagination ni de filtres (review statique V1).

---

## Addendum data — B1 (per-run agent snapshot)

### Problème

Overlay Agent du graphe (Épiques 04/05) : input + output + ELO deltas viennent du graphe ; **system prompt** et **ELO courant** n'y sont pas → join `agent_id`→`/api/agents/<id>`. Or `registry.json` est réécrit à chaque run (ids régénérés), donc une session/HC historique pointe des ids absents du registry courant → 404, overlay sans prompt.

### Solution (B1)

Figer l'identité des agents **à côté de la trace**, au moment de la sauvegarde. L'overlay joint contre ce snapshot, jamais périmé, et reflète l'état au run-time (prompt + ELO du moment — correct pour une review historique). Le registry global reste le **roster courant** de Tab 2, **non pollué**.

### Changements (additifs — aucun schéma existant modifié)

**Backward compat** : le param `agents` est **optionnel** (`agents: list[Agent] | None = None`, pattern projet `llm_metadata`/`evaluator`). Si fourni → écrit `agents.json` ; si `None` → comportement 03a inchangé (pas de fichier). Les call sites existants (tests unitaires de `store`/`health_check`) ne bougent pas ; seuls la démo et la fixture dashboard passent des agents réels.

| Élément | Emplacement | Action |
|---|---|---|
| `save_session(tracer, meta, runs_root, agents=None)` | `tracing/store.py` | + param optionnel `agents: list[Agent] \| None` → si fourni, écrit `sessions/<id>/agents.json` (un `AgentRegistry`) |
| `save_health_check(report, test_set, tracer, directory, agents=None)` | `qa/health_check.py` | idem → `<directory>/<ts>/agents.json` |
| construction des entrées | `tracing/store.py` | factoriser un helper depuis `save_agent_registry` (réutilise `AgentRegistryEntry`) |
| `run_demo.py` / `run_health_check.py` | `demo/` | passent leurs agents aux fonctions de sauvegarde |
| fixture `runs_root` | `tests/dashboard/conftest.py` | écrit `agents.json` dans le dir session **et** health check |

Modèles `AgentRegistry` / `AgentRegistryEntry` (déjà `agent_id` + `name` + `system_prompt` + `tags_with_elo`) réutilisés tels quels. Les collectors lisent `agents.json` par `AgentRegistry.model_validate_json` quand il existe ; absent → `agents = []` (overlay dégrade proprement, n'arrive que sur des saves sans agents, jamais via démo/fixture).

### Convention de store après B1

```
runs_root/
  agents/registry.json                       # roster courant (Tab 2)
  sessions/<id>/{trace.jsonl, meta.json, agents.json}      # agents.json NOUVEAU
  health_checks/<ts>/{report.json, test_set.json, trace.jsonl, agents.json}  # agents.json NOUVEAU
```

---

## Couche HTTP (`dashboard/`)

### Structure

```
dashboard/
  serialization.py   json_response(model, status=200) / error_response(msg, status=404)
  api.py             Blueprint("api", url_prefix="/api") + routes
  app.py             create_app : enregistre le blueprint (+= ligne)
```

### Helpers de sérialisation (`serialization.py`)

- `json_response(model: BaseModel, status: int = 200) -> Response`
  - `jsonify(model.model_dump(by_alias=True, mode="json"))`, code `status`, header `Cache-Control: no-store`.
- `error_response(msg: str, status: int = 404) -> Response`
  - `jsonify({"error": msg})`, code `status`, header `Cache-Control: no-store`.

### Endpoints (`api.py`)

| Endpoint | Source (collector 03a) | Renvoie | 404 si |
|---|---|---|---|
| `GET /api/infra` | `infra.collect` | `InfraStats` | — |
| `GET /api/agents` | `agents.list_agents` | `AgentList` (roster courant) | — |
| `GET /api/agents/<id>` | `agents.agent_detail` | `AgentDetailView` | détail `None` |
| `GET /api/sessions` | `sessions.list_sessions` | `SessionList` | — |
| `GET /api/sessions/<id>` | `sessions.session_detail` | meta + agents du run (**pas le graphe**) | détail `None` |
| `GET /api/sessions/<id>/graph` | `sessions.session_detail` | `GraphModel` nu | détail `None` |
| `GET /api/health-checks` | `health_checks.list_runs` | `HealthCheckList` | — |
| `GET /api/health-checks/<id>` | `health_checks.run_detail` | détail (report+cases) + agents du run | détail `None` |
| `GET /api/health-checks/<id>/graph?task_id=` | `health_checks.case_graph` | `GraphModel` d'un cas ; sans `task_id` → 1er cas graphable | run absent / aucun cas graphable |

Le cache 03a (`get_or_compute`) est branché sur les vues immuables-par-id (détails, graphes) ; les listes/agrégats restent recalculés (reflètent les nouveaux runs sans redémarrage), cohérent avec la stratégie 03a.

### Conséquences sur les collectors 03a (additif, dans `dashboard/`)

- `sessions` : le détail expose désormais `agents` (lu de `agents.json`). Le contrat S3-A sépare meta/graph côté HTTP — `session_detail` peut continuer à porter le `GraphModel` ; la route `/<id>` sérialise meta + agents (sans le graphe), la route `/<id>/graph` sérialise `.graph`. (Factoring exact tranché en writing-plans.)
- `health_checks` : `run_detail` expose `agents` du run.
- `/api/agents/<id>` reste réservé à Tab 2 (roster courant) ; les overlays graphe (Tab 3 & 4) joignent contre les `agents` portés par le détail du run (B1).

---

## Stratégie de test (TDD)

- **Addendum data B1** : `save_session(..., agents=...)` / `save_health_check(..., agents=...)` écrivent un `agents.json` relisible en `AgentRegistry` ; appelés sans `agents` (défaut `None`) → comportement 03a inchangé (pas de fichier, call sites existants intouchés).
- **Sérialisation** : `json_response` pose `Cache-Control: no-store`, sérialise un `GraphEdge` en `{"from", "to"}` (vérifie `by_alias`), convertit datetime→ISO ; `error_response` renvoie `{"error": ...}`.
- **API (`test_client`)** sur `create_app(config_test)` + fixture `runs_root` :
  - chaque endpoint : code 200, `Content-Type` JSON, header `Cache-Control: no-store`.
  - `<id>` inconnu → 404 + corps `{"error": ...}`.
  - endpoints graphe → `GraphModel` valide (session = steps ordonnés ; HC = 1 run/cas, `task_id` par défaut = 1er graphable, `task_id` de quarantaine → 404).
  - détails session + HC : champ `agents` présent et non vide (vérifie B1 de bout en bout).
- **Non-régression** : les 557 tests existants restent verts (param `agents` optionnel → call sites inchangés ; seule la fixture dashboard ajoute les `agents.json`).

## Critères de done

- [ ] B1 : `save_session` / `save_health_check` écrivent `agents.json` ; démos + fixture mises à jour.
- [ ] Tous les endpoints du tableau répondent en JSON via `json_response`.
- [ ] `Cache-Control: no-store` présent sur tous les endpoints data (succès **et** 404).
- [ ] Endpoints graphe câblés sur `build_graph` (session steps ; HC `task_id` avec défaut 1er cas graphable).
- [ ] Détails session + HC portent les agents du run (join overlay robuste).
- [ ] Tests `test_client` verts (succès + 404) ; non-régression complète.

## Découpe pressentie (détaillée en writing-plans)

1. **Addendum data B1** : `save_session`/`save_health_check` + param `agents`, helper d'entrées, démos, fixture `agents.json` (+ collectors `sessions`/`health_checks` exposant `agents`).
2. **Sérialisation** : `serialization.py` (`json_response` / `error_response`).
3. **API** : `api.py` blueprint + routes, enregistrement dans `create_app`.
4. **Non-régression** : suite complète + cycle d'import propre.
