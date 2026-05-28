# V2c — Épique 3b — API REST

- **Couche** : `dashboard/` (côté serveur — exposition HTTP)
- **Statut** : à creuser (deep-dive → plan → impl)
- **Dépendances** : Épique 3a (collectors + cache + factory), Épique 2 (`build_graph` pour les endpoints graphe).
- **Spec source** : Section 2 — API REST.

## Contexte

Deuxième moitié du backend : la couche HTTP qui expose les collectors (Épique 3a) et `build_graph` (Épique 2) en JSON. Testée via `test_client` Flask sur `create_app(config_test)`. C'est le contrat que le frontend (Épiques 4-5) consomme.

## Décisions portées

- **#3** — `Cache-Control: no-store` sur les endpoints data (comme aios). Pas de live mode.

## Endpoints

| Endpoint | Sert | Source |
|---|---|---|
| `GET /api/infra` | Tab 1 | collector `InfraStats` |
| `GET /api/agents` · `GET /api/agents/<id>` | Tab 2 | collector `Agents` |
| `GET /api/health-checks` · `GET /api/health-checks/<id>` · `GET /api/health-checks/<id>/graph?task_id=` | Tab 3 | collector `HealthChecks` + `build_graph` (un cas) |
| `GET /api/sessions` · `GET /api/sessions/<id>` · `GET /api/sessions/<id>/graph` | Tab 4 | collector `Sessions` + `build_graph` (steps) |

## Stratégie de test (TDD)

- Tests Flask `test_client` sur `create_app(config_test)` pointant un `runs_root` fixture.
- Vérifier : codes HTTP, forme JSON, header `Cache-Control: no-store`, endpoints graphe qui renvoient un `GraphModel` valide (session = steps ordonnés ; health check = un run/cas + pass_rate).
- Cas d'erreur : `<id>` inconnu → 404.

## Critères de done

- [ ] Tous les endpoints du tableau répondent en JSON.
- [ ] `Cache-Control: no-store` présent sur les endpoints data.
- [ ] Endpoints graphe câblés sur `build_graph` (param `task_id` pour le health check).
- [ ] Tests `test_client` verts (succès + 404).

## À creuser en session de deep-dive

- Blueprint vs routes directes sur l'app factory.
- Sérialisation du `GraphModel` (dict pur → `jsonify` direct, ou modèle Pydantic ?).
- Sémantique de `/api/health-checks/<id>/graph?task_id=` quand `task_id` absent (premier cas ? liste des cas dispo ?).
- Cohérence des payloads avec ce que le frontend (Épique 4) attend pour l'overlay.
