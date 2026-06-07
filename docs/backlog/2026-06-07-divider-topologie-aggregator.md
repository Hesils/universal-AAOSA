# Backlog — Topologie du divider : chaînes pures → aggregator jamais sollicité

**Découvert** : 2026-06-07, validation DoD démo phase 3 (session `runs/sessions/2026-06-07T13-20-39-730273e3`, scénario `main`).
**Constat de Quentin au sign-off** : aucun nœud AGGREGATOR ne s'affiche sur le graphe d'un run divisé réel.
**TRANCHÉ 2026-06-07 (phase 4)** : option « retirer la consigne synthèse » retenue — voir « Décision et résultat d'observation » en bas. Le ticket reste ouvert UNIQUEMENT pour l'observation N=20 de phase 5.

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

## Options discutées (2026-06-07, tranchées en phase 4 — cf. bas de ticket)

- **Assumer la synthèse par agent** : la synthèse passe par claiming + QA + ELO (dans le run : client-comm a écrit le Final Incident Report, QA 0.79, ELO à jour). L'aggregator reste un filet pour les vrais fan-ins. Cohérent AAOSA-spirit ; mais l'aggregator ne sera jamais démontrable.
- **Retirer la consigne synthèse** (et/ou adoucir « ordered ») : le divider décide librement → certaines découpes auront des sinks par domaine → l'aggregator tourne et apparaît au graphe. Émergence pure ; mais la synthèse sort du roster.
- Nuance claiming observée : le tagger a tagué la sous-tâche synthèse `{communication, writing}` → c'est client-comm qui a synthétisé un incident sécurité+RGPD. Défendable (travail de rédaction), mais le « bon » rôle de synthèse est discutable.

## Question ouverte associée (trou qualité)

**L'output de l'aggregator n'est pas QA-évalué** — l'agrégation arrive après les QA des sous-tâches, et son résultat part tel quel (`agent_id="aggregator"`, fallback `sinks[-1]` sur exception). Si l'aggregator devient fréquent, c'est un trou de contrôle qualité en bout de pipeline (candidat « D5 »). La synthèse par agent, elle, est QA-évaluée.

**RE-DÉFERRÉ EXPLICITEMENT EN D5 (2026-06-07, spec phase 4 §2)** : phase 4 = chantier CLI, zéro changement runtime. La campagne phase 5 fournit les données (fréquence réelle des agrégations, qualité perçue) pour trancher D5. D'autant plus défendable que l'observation phase 4 donne 0 agrégation sur 7 runs (cf. bas de ticket).

## Quand traiter

Au plus tard **phase 4 (CLI `run`/`campaign`)** : les prompts divider/aggregator/tagger migreront des scripts jetables vers le CLI — c'est le moment naturel pour trancher la formulation. Pour la **campagne** (phase 5), des graphes variés (avec et sans aggregator) seraient un argument démo fort (« le graphe d'exécution n'est pas connu à l'avance »). **→ Traité en phase 4, cf. ci-dessous.**

## Critères d'acceptation (une fois tranché)

- [x] Décision loggée (retirer la consigne) avec re-runs réels de validation (7 runs, 2026-06-07).
- [ ] Si « retirer » : observer ≥1 run réel avec `TaskAggregatedEvent` dans la trace et nœud AGGREGATOR au dashboard. **Constat zéro sur n=7 (phase 4) — reporté sur la N=20 de phase 5, on n'inverse pas la décision (spec phase 4 §6).**
- [x] La question QA-aggregator est explicitement re-déferrée en D5 (spec phase 4 §2).

## Décision et résultat d'observation (2026-06-07, phase 4)

**Décision** : « Retirer la consigne synthèse » + adoucir « ordered » (spec `docs/superpowers/specs/2026-06-07-v3-demo-phase4-cli-design.md` §6). Prompt réécrit dans `src/aaosa/demo/incident/prompts.py` (single home, `DIVIDER_PROMPT`) ; décision verrouillée par tests (`tests/demo/incident/test_prompts.py` : pas de « synthesis », pas de « ordered », « only when » présent).

**Observation DoD (mini-campagne n=5 + 2 runs unitaires, gpt-4o-mini temp 0)** :
- **0 `TaskAggregatedEvent` sur 7 runs.** Les 6 runs divisés (5 campagne + 1 unitaire) produisent TOUS une chaîne pure de 5 sous-tâches (deps strictement linéaires, vérifié programmatiquement sur les traces) → 1 sink → court-circuit D2 systématique.
- Lecture : même sans « ordered »/« synthesis », gpt-4o-mini à temp 0 décompose linéairement cette tâche (le récit incident induit une séquence investigation → scope → réglementaire → communication). Le retrait du prompt était nécessaire (la découpe hardcodée violait « le graphe émerge ») mais pas suffisant pour faire apparaître des fan-ins sur CETTE tâche.
- Conformément à la décision : **constat documenté, la N=20 de phase 5 tranche, on n'inverse pas.** Si la N=20 donne aussi zéro, options à réévaluer en connaissance de cause (autre tâche-mère moins séquentielle, température divider, ou assumer « l'aggregator = filet pour les vrais fan-ins, rare par nature »).

**Note technique (review phase 4)** : au top-level, un échec QA non récupéré remonte en `DispatchResult(status="qa_failed")`, jamais en `QAFailure` (`_route_diagnostic` le convertit toujours) — le mapping d'index du CLI le gère via `_result_kind` (`src/aaosa/cli/incident_runs.py`).

## Pointeurs

- Mécanique sinks : `src/aaosa/runtime/runner.py` (`_sinks`, `_divide_and_recover` lignes ~299-306) ; règle dashboard dupliquée `_graph_sinks` (`dashboard/graph_model.py`).
- Prompts : `src/aaosa/demo/incident/prompts.py` (single home depuis phase 4 — `run_incident.py` et `run_demo_v3.py` supprimés) ; verrous `tests/demo/incident/test_prompts.py`.
- Design D2 : bloc « Agrégation par sinks (D2) » dans `CLAUDE.md` ; plan `docs/superpowers/plans/2026-06-05-d2-aggregateur-dag-aware.md`.
- Données d'observation phase 4 : `runs_campaign_p4/campaign_index.json` (worktree phase 4) — 5/5 `success [divided]`.
- Lié au ticket `2026-06-07-dataflow-edges-dashboard.md` (visibilité du flux dans les chaînes).
