# Backlog — Topologie du divider : chaînes pures → aggregator jamais sollicité

**Découvert** : 2026-06-07, validation DoD démo phase 3 (session `runs/sessions/2026-06-07T13-20-39-730273e3`, scénario `main`).
**Constat de Quentin au sign-off** : aucun nœud AGGREGATOR ne s'affiche sur le graphe d'un run divisé réel.

## Diagnostic (complet, pas de recherche à refaire)

Le rendu est fidèle : **zéro `TaskAggregatedEvent` dans la trace**. Mécanique D2 (`run_with_recovery` / `_sinks`, `src/aaosa/runtime/runner.py`) : 1 sink → court-circuit (l'output du sink est le résultat, zéro appel aggregator) ; ≥2 sinks → `aggregator.aggregate`. Or le divider (gpt-4o-mini, temp 0) a produit **trois chaînes purement linéaires** dans ce run :

```
racine     : [1]→[2]→[3]→[4]→[5]→[6 synthèse]   (6 sous-tâches)
imbriquée 1: [1]→[2]→[3]→[4 synthèse]
imbriquée 2: [1]→[2]→[3]→[4 synthèse]
```

Chaque output est consommé par le suivant → le dernier maillon est toujours l'unique sink → court-circuit systématique. **Deux causes qui se renforcent** dans le system prompt du divider (défini dans `run_incident.py` et identique dans `run_demo_v3.py`) :

1. « include a final synthesis sub-task » — garantit un consommateur terminal unique (découpe hardcodée dans le prompt, en tension avec la séparation stricte V3 « le graphe émerge : aucune découpe hardcodée »).
2. « minimal set of **ordered** sub-tasks » — pousse le modèle vers du strictement séquentiel ; même sans la consigne synthèse, une chaîne pure n'a qu'un sink.

Conséquences : l'aggregator LLM est du code mort en pratique (D2, conçu pour les multi-sinks, ne voit jamais de multi-sinks) ; la paire DIVIDER/AGGREGATOR construite par l'observabilité phase 1 n'apparaît jamais en run réel ; le DAG sérialisé interdit tout parallélisme futur de `run_chain`.

## Options discutées (2026-06-07, non tranchées)

- **Assumer la synthèse par agent** : la synthèse passe par claiming + QA + ELO (dans le run : client-comm a écrit le Final Incident Report, QA 0.79, ELO à jour). L'aggregator reste un filet pour les vrais fan-ins. Cohérent AAOSA-spirit ; mais l'aggregator ne sera jamais démontrable.
- **Retirer la consigne synthèse** (et/ou adoucir « ordered ») : le divider décide librement → certaines découpes auront des sinks par domaine → l'aggregator tourne et apparaît au graphe. Émergence pure ; mais la synthèse sort du roster.
- Nuance claiming observée : le tagger a tagué la sous-tâche synthèse `{communication, writing}` → c'est client-comm qui a synthétisé un incident sécurité+RGPD. Défendable (travail de rédaction), mais le « bon » rôle de synthèse est discutable.

## Question ouverte associée (trou qualité)

**L'output de l'aggregator n'est pas QA-évalué** — l'agrégation arrive après les QA des sous-tâches, et son résultat part tel quel (`agent_id="aggregator"`, fallback `sinks[-1]` sur exception). Si l'aggregator devient fréquent, c'est un trou de contrôle qualité en bout de pipeline (candidat « D5 »). La synthèse par agent, elle, est QA-évaluée.

## Quand traiter

Au plus tard **phase 4 (CLI `run`/`campaign`)** : les prompts divider/aggregator/tagger migreront des scripts jetables vers le CLI — c'est le moment naturel pour trancher la formulation. Pour la **campagne** (phase 5), des graphes variés (avec et sans aggregator) seraient un argument démo fort (« le graphe d'exécution n'est pas connu à l'avance »).

## Critères d'acceptation (une fois tranché)

- Décision loggée (assumer / retirer la consigne / autre) avec re-run réel de validation.
- Si « retirer » : observer ≥1 run réel avec `TaskAggregatedEvent` dans la trace et nœud AGGREGATOR au dashboard.
- La question QA-aggregator est tranchée ou explicitement re-déferrée.

## Pointeurs

- Mécanique sinks : `src/aaosa/runtime/runner.py` (`_sinks`, `_divide_and_recover` lignes ~299-306) ; règle dashboard dupliquée `_graph_sinks` (`dashboard/graph_model.py`).
- Prompts : `src/aaosa/demo/incident/run_incident.py` (divider/aggregator/tagger) ; mêmes prompts dans `src/aaosa/demo/run_demo_v3.py`.
- Design D2 : bloc « Agrégation par sinks (D2) » dans `CLAUDE.md` ; plan `docs/superpowers/plans/2026-06-05-d2-aggregateur-dag-aware.md`.
- Lié au ticket `2026-06-07-dataflow-edges-dashboard.md` (visibilité du flux dans les chaînes).
