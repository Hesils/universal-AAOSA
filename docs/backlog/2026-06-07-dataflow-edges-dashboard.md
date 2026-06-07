# Backlog — Visibilité du flux de données inter-sous-tâches (dashboard)

**Découvert** : 2026-06-07, validation DoD démo phase 3 (session `runs/sessions/2026-06-07T13-20-39-730273e3`, scénario `main`).
**Constat de Quentin au sign-off** : « sur la vue graph, l'impression que ça donne c'est que l'information ne redescend jamais après les evaluators sauf pour l'output final » — alors que les outputs SONT repassés aux tâches suivantes (`required_outputs`) et qu'il existe des liens entre sous-tâches au-delà du divider comme origine commune.

## Symptôme

Sur un run divisé en chaîne (sous-tâche N+1 dépend de N), le graphe rend visuellement un arbre pur : chaque branche se termine à son EVALUATOR, seule la branche finale descend vers OUTPUT. Le passage de l'output de N vers le dispatch de N+1 est invisible.

## Cause (diagnostiquée, pas de recherche à refaire)

Les arêtes de dépendance **existent dans le modèle** mais ne sont jamais mises en valeur :

1. `dashboard/graph_model.py:405-412` (fonction `visit` dans le builder nodes/edges) : pour chaque dépendance satisfaite, émet `exit(dep) → dispatch(consommateur)` en flow `"transient"`. L'`exit` d'une sous-tâche réussie est son nœud `evaluator` — vérifié sur la session ci-dessus : les 11 evaluators ont bien leurs arêtes sortantes dans `graph.edges`.
2. **Aucun `GraphStep` ne les active** : au jalon DISPATCH du consommateur (builder des steps, ~`graph_model.py:788-793`), le `fan` passé à `acc.snapshot(fan)` ne contient pas les arêtes entrantes de dépendance (seulement le loop-back diag→dispatch au retry).
3. `dashboard/static/js/graph.js:284` : les pulses directionnels sautent explicitement le flow `transient`.

Résultat : ces arêtes sont dessinées en fil pointillé idle (une fois les deux extrémités révélées, `revealUpTo` → `edge: vis(from) && vis(to)`), jamais allumées, jamais pulsées → quasi invisibles.

## Fix proposé

Au jalon DISPATCH (pass 0) d'une sous-tâche consommatrice, ajouter au `fan` les arêtes `(exit(dep), dispatch_id, "transient")` pour chaque dépendance satisfaite → pendant le replay, l'output de [N] « descend » visuellement vers [N+1] au moment où elle est dispatchée. Éventuellement : style CSS dédié pour distinguer flux-de-données des autres transient (fan-out claiming).

- Backend : TDD sur `build_graph` (asserter que le step dispatch du consommateur contient l'arête de dépendance dans `active_edges`).
- Le builder steps doit accéder aux deps + à l'état `runs` (les deux existent déjà dans le scope — voir le builder nodes/edges qui fait le même calcul ; attention à la duplication de la logique `_exit_node`).
- Frontend : rien d'obligatoire (l'activation suffit à allumer l'arête), pulses optionnels.

## Critères d'acceptation

- Sur la session `2026-06-07T13-20-39-730273e3` (ou un run divisé équivalent), au step DISPATCH d'une sous-tâche dépendante, l'arête `evaluator(dep) → dispatch` s'allume.
- Non-régression : tabs Health/Sessions existants, suite `tests/dashboard/` verte.
- Validation navigateur (le rendu graphe est hors TDD auto — convention V2c).

## Contexte connexe

- Convention phase 1 observabilité : « arêtes backbone cumulatives, fan-out transitoires » — ce ticket ne remet pas en cause la distinction, il active les transient de dépendance à leur jalon.
- Lié au ticket `2026-06-07-divider-topologie-aggregator.md` : tant que le divider produit des chaînes, ces arêtes de dépendance sont le SEUL endroit où la structure du DAG est visible.
