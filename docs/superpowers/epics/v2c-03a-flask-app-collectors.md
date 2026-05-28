# V2c — Épique 3a — App Flask, cache & collectors

- **Couche** : `dashboard/` (côté serveur — agrégation)
- **Statut** : à creuser (deep-dive → plan → impl)
- **Dépendances** : Épique 1 (store/runs_root), Épique 2 (pour les collectors qui dérivent des agrégats de traces).
- **Spec source** : Section 2 — `create_app`, `cache`, collectors.

## Contexte

Première moitié du backend : l'infrastructure de l'app Flask + la **logique d'agrégation** (collectors). Les collectors sont des fonctions/classes Python testables sur un `runs_root` fixture, indépendamment de la couche HTTP (Épique 3b). On sépare ainsi l'agrégation (testée sur arborescence de fichiers) de l'exposition REST (testée via `test_client`).

## Décisions portées

- **#3** — Serveur Flask à la aios-dashboard : `create_app(config)` **factory testable**, **cache in-memory on-demand** (pas de DB, pas de TTL), **pas de live mode** (V1 = review statique sur runs persistés).
- **#4** — App dans `dashboard/` à la racine ; consomme la couche data de `src/aaosa/`.

## Structure (périmètre 3a)

```
dashboard/
  app.py                # create_app(config) factory
  config.py             # runs_root, host, port
  cache.py              # cache in-memory on-demand
  collectors/
      infra.py          # Tab 1
      agents.py         # Tab 2
      health_checks.py  # Tab 3
      sessions.py       # Tab 4
  tests/
```

## Collectors

| Collector | Tab | Source | Sortie |
|---|---|---|---|
| `InfraStats` | 1 | tous les `sessions/*/trace.jsonl` | nb sessions/runs/agents/tasks, distribution latence, tokens in/out, QA pass rate global, pass rate dans le temps |
| `Agents` | 2 | `agents/registry.json` + `elo_snapshots/*` + traces | par agent : prompt, tags+ELO courant, **historique ELO par tag** (séries horodatées), historique claim/win/success/fail |
| `HealthChecks` | 3 | `health_checks/*` | liste runs ; par run : pass rates fix_target/regression_guard, cas unstable, buckets quarantaine, TestSet (split train/test, evaluator + attribution par cas) |
| `Sessions` | 4 | `sessions/*` | liste sessions ; par session : meta + trace |

## Cache

In-memory on-demand : un agrégat est calculé au premier accès puis mémorisé. Pas de TTL, pas d'invalidation live (V1 statique). À aligner sur le pattern aios-dashboard.

## Stratégie de test (TDD)

- Tests sur un `runs_root` fixture (arborescence de fichiers réelle) → agrégats attendus par collector.
- Test du cache : second accès ne recalcule pas (ou retourne la valeur mémorisée).
- `create_app(config_test)` instanciable sans serveur lancé.

## Critères de done

- [ ] `create_app(config)` factory + `config.py` + `cache.py` en place, instanciables en test.
- [ ] Les 4 collectors produisent les agrégats attendus sur un `runs_root` fixture.
- [ ] Cache in-memory on-demand fonctionnel et testé.
- [ ] Aucun endpoint HTTP encore (réservé Épique 3b).

## À creuser en session de deep-dive

- Pattern exact `create_app` / cache de l'aios-dashboard (lire le repo aios_dashboard comme référence).
- Frontière précise collector ↔ `graph_model` : les collectors listent/agrègent, `build_graph` (Épique 2) produit le graphe ; qui appelle qui.
- Construction de l'historique ELO par tag (séries horodatées depuis `elo_snapshots/*`).
- Forme du `runs_root` fixture partagé avec les tests de l'Épique 3b.
