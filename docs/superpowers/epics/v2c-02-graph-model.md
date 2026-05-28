# V2c — Épique 2 — Modèle de graphe (`build_graph`)

- **Couche** : `dashboard/graph_model.py` (fonction pure)
- **Statut** : à creuser (deep-dive → plan → impl)
- **Dépendances** : Épique 1 (events enrichis, `ExecutedEvent.llm_metadata`).
- **Spec source** : Section 2 — sous-section "Modèle de graphe".

## Contexte

Le cœur testable du dashboard : transformer une trace d'events en un modèle de graphe navigable à 3 couches. Fonction pure → entièrement couverte par des tests sur fixtures, sans Flask ni frontend. C'est le pont entre la donnée persistée (Épique 1) et l'affichage (Épiques 4-5).

## Décisions portées

- **#1** — Graphe = **pipeline réel uniquement**, modèle de nœud générique/extensible. Pas de nœud fantôme V3.
- **#2** — Topologie en **3 couches spatiales** : TOP (I/O système : input, retour user, TestSet), CENTER (logique : Dispatch=claiming collapse, Evaluator), BOTTOM (agents). Le `layer` de chaque nœud est posé ici. Le layout réserve la place pour les nœuds V3 (TaskDivider, Aggregateur, tools) sans les produire.
- **#5** — Comportement différencié Tab 3 vs Tab 4 (voir ci-dessous).

## Signature & structure

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

## Comportement Tab 4 vs Tab 3

- **Tab 4 (session)** : `steps` = un par task, dans l'ordre des timestamps → alimente le scrubber + le panneau todo.
- **Tab 3 (health check)** : un `GraphModel` par cas sélectionné (le sélecteur de task choisit le cas) ; **pas de stepping**. Le `trace.jsonl` du health check contient les N runs de chaque cas — le builder ne retient **qu'un run par cas** (le dernier) pour le graphe, et affiche le `pass_rate` agrégé du cas (ex. 4/5) en annotation.

## Mapping events → état

- `Phase1FilteredEvent` (passed, fit_score) → état agent (filtré/passé) + payload overlay Dispatch
- `Phase2ClaimedEvent` (decision, justification) → claim agent + payload overlay
- `DispatchedEvent` (agent_id, reason) → winner
- `ExecutedEvent` (output_summary, llm_metadata) → output du winner + overlay agent
- `QAEvaluatedEvent` (success, score, reason) → état Evaluator + fork pass/fail
- `EloUpdatedEvent`, `TagAcquiredEvent` → effets ELO (overlay agent)
- `UnassignedEvent` → pas de winner

## Stratégie de test (TDD)

Fonction pure → tests sur traces fixtures couvrant :
- run assigned (winner + output + QA pass)
- run unassigned (`UnassignedEvent`, pas de winner)
- multi-claim (plusieurs Phase2ClaimedEvent → résolution)
- QA fail → fork branche fail + lien TestSet
- session multi-task (ordre des `steps` par timestamp)
- cas health check : N runs d'un même cas → un seul run retenu + `pass_rate` annoté

## Critères de done

- [ ] `build_graph` produit nodes/edges/steps conformes pour les 6 scénarios fixtures.
- [ ] Layers TOP/CENTER/BOTTOM correctement assignés par type de nœud.
- [ ] Mode session (steps ordonnés) et mode health check (un run/cas + pass_rate) couverts.
- [ ] Aucun nœud V3 produit.
- [ ] Tests verts, fonction sans effet de bord.

## À creuser en session de deep-dive

- Inventaire exact des classes d'events dans `tracing/events.py` (noms, champs) — la liste ci-dessus est à confirmer contre le code.
- Comment `session_meta` (Épique 1) s'articule avec les events pour produire les `label` et l'ordre des steps.
- Forme précise du `detail` overlay par type de nœud (sera consommé par l'Épique 4 — aligner les payloads).
- Identification "dernier run" d'un cas health check dans un `trace.jsonl` multi-runs.
