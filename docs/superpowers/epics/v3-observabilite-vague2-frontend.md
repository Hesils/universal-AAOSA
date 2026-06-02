# V3 Observabilité — Vague 2 (frontend) : graphe cumulatif, couche tools, TODO d'achèvement

Date : 2026-06-02
Statut : deep-dive validé (shape impeccable), prêt pour plan d'implémentation
Prérequis : **vague 1** (events) mergée — ce design suppose `TaskDividedEvent.sub_tasks`, `QAEvaluatedEvent.spec`, `ToolCalledEvent` émis dans le chemin runtime. Spec vague 1 : `docs/superpowers/specs/2026-06-02-v3-demos-end-to-end-design.md`. Plan vague 1 : `docs/superpowers/plans/2026-06-02-v3-observabilite-vague1.md`.
Design system : `DESIGN.md` + `PRODUCT.md` (racine) — direction « wireframe instrument » (verrouillée, aucun override).

## Objectif

Transformer le graphe d'exécution du tab Sessions d'un **instantané par tâche** en un **rejeu cumulatif jalon-par-jalon d'un run unique**, gérant les runs divisés (chaîne de sous-tâches émergente), une 4e tier `tools`, et une TODO vivante d'achèvement de l'input. Cible : Quentin lit « comment le graphe s'est construit » en un scrub, sans JSONL.

## Périmètre (décisions verrouillées)

- **Tab Sessions uniquement** + la réécriture de `build_graph` (fonction partagée → met aussi à jour les case-graphs du health tab au passage).
- **Couche tools** : canopée idle visible dès le départ (les hexes tools du run, peu nombreux, en wireframe idle ; le lien `agent→tool` s'allume à l'appel). Bande rendue seulement si le run a une activité tool.
- **Parcours B2/B3** (triage→fix→re-triage observable) : **différé** (resterait en état final dans le health tab).
- Aucune nouvelle langue visuelle : on étend l'instrument verrouillé.

## État actuel (point de départ)

`dashboard/static/js/`:
- `graph.js` — `renderGraph(svg, graph, activeStepIndex, onNodeClick, agentNames)`. 3 bandes (`top`/`center`/`bottom`), arbre inversé (`bottom`=agents=leaves en haut, `center`=trunk, `top`=roots/io en bas). Par step : `active_nodes`/`active_edges` du `GraphStep` (modèle per-tâche). Winner brûle, branche fail pointillée, pulses ember sur arêtes actives.
- `sessions.js` — layout déjà en place : `.graph-frame` (graphe) + aside `.todo` (« Tasks ») + `.scrubber`. `renderTodo()` existe (liste `detail.meta.tasks`, états done/current/pending par index de step).
- `modal.js` — `openNodeModal(node, step, runAgents)` ; cases : dispatch/agent/evaluator/input/output/testset. **Pas** de case divider/aggregator/tool ; `tool_calls_count` non affiché.
- `graph_model.py` (`build_graph`) — pur ; `GraphStep` per-tâche avec `active_nodes`/`active_edges` = chemin complet de la tâche.

## Direction visuelle

Restrained chrome + graphe ember (DESIGN.md), dark. Scène inchangée (ingénieur revoyant un run fini, pièce sombre, données denses). Ancrages : le graphe wireframe existant ; un **affichage à persistance d'oscilloscope** (la trace se construit et reste) ; un **schéma de circuit** (tiers + nœuds hex).

## Layout

Conserver le split : `graph-frame` dominant gauche, aside `Tasks` (TODO) rail droit, `scrubber` pleine largeur dessous. Le graphe gagne une **4e bande tout en haut** (les tools = croissance la plus périphérique, « au-dessus des feuilles ») :

```
tools · capabilities     ← nouveau (canopée idle, conditionnelle)
leaves · agents
trunk · logic
roots · in/out
```

`layout()` : 3 → 4 bandes. Bande tools rendue ssi le run a une activité tool (même pattern conditionnel que divider/aggregator).

## Modèle cumulatif par jalons (cœur)

Le scrubber avance **d'un jalon** (plus d'une tâche). Jalons curés : `INPUT`, `DIVIDER`, `DISPATCH`, `AGENT`, `TOOL`, `EVALUATOR`, `AGGREGATOR`, `OUTPUT` (les events Phase1/Phase2 par agent sont regroupés dans le jalon `DISPATCH` ; son modal résume candidats + justifications).

Modèle d'allumage :
- **Nœuds** : seul le nœud actif du jalon brûle (ember) ; les autres (dont la canopée tools) restent en wireframe idle.
- **Liens backbone** (root↔trunk, peu nombreux) : `input→divider`, `divider→dispatch`, `evaluator→aggregator`, `aggregator→output` — **cumulatifs et persistants**.
- **Liens fan-out** (nombreux) : `dispatch→agent`, `agent→tool`, **`agent→evaluator` (verrouillé fan-out)** — **transitoires** : seul celui de la sous-tâche / de l'appel courant est allumé ; éteint à la résolution de la sous-tâche (lue via `QAEvaluatedEvent.success`), le jalon suivant allume le lien du nouveau winner.

Séquence canonique (run divisé) :

```
INPUT            input actif ; lit {}
DIVIDER          divider actif ; backbone +input→divider ; TODO expand sous-tâches
  (par sous-tâche k, dans l'ordre topologique)
  DISPATCH·k     dispatch actif ; backbone +divider→dispatch
  AGENT·k        agent winner_k actif ; fan-out dispatch→agent_k (transitoire)
  TOOL·k (×n)    tool actif ; fan-out agent_k→tool (transitoire) ; dispatch→agent_k reste tant que k actif
  EVALUATOR·k    evaluator actif ; fan-out agent_k→evaluator (transitoire)
                 → QA pass : TODO raye k ; fan-out de k éteints
                 → QA fail : branche evaluator→testset (style --fail) ; TODO marque k échec
AGGREGATOR       aggregator actif ; backbone +evaluator→aggregator
OUTPUT           output actif ; backbone +aggregator→output
```

Run simple (pas de divide/tool) : `INPUT→DISPATCH→AGENT→EVALUATOR→OUTPUT`, aucune bande tools/divider/aggregator (comportement actuel préservé).

## États clés

- **Run simple** — comportement actuel préservé.
- **Run outillé non divisé** — bande tools (canopée idle), `agent→tool` à l'appel.
- **Run divisé** — séquence canonique ci-dessus.
- **Sous-tâche QA fail** — branche `evaluator→testset` (`--fail` pointillé existant) ; item TODO marqué échec (pas rayé).
- **Sous-tâche unassigned** — dispatch sans winner ; item TODO signalé.
- **Fallback aggregator** (aggregate() a levé) — output = dernier sous-output réussi ; modal Aggregator indique le fallback.
- **Premier jalon** — seul `input` allumé, TODO = input seul.
- **Empty** — placeholder existant.

## Contenu / copy

- Tier label : `tools · capabilities` (mono, faible, comme les `TIER_LABEL`).
- Labels scrubber (mono) : `INPUT`, `DIVIDER`, `DISPATCH · sous-tâche k`, `AGENT · <nom>`, `TOOL · <tool_name>`, `EVALUATOR · sous-tâche k`, `AGGREGATOR`, `OUTPUT`.
- TODO : description input (racine) + descriptions sous-tâches (depuis `TaskDividedEvent.sub_tasks`). États : pending / current / done (rayé) / failed.
- Nouveaux modals :
  - **Divider** : liste des sous-tâches générées + `depends_on`.
  - **Aggregator** : output synthétisé + flag fallback + quels sous-outputs agrégés.
  - **Tool** : `tool_name`, `arguments`, `result`, `latency_ms` (mono).
  - **Evaluator étendu** : la **spec générée complète** (critères + descriptions `llm_check` + poids + seuil + judge) depuis `QAEvaluatedEvent.spec`, en plus des criteria_results/score actuels.

## Dépendance backend : réécriture `build_graph`

Socle de la vague 2. `GraphStep` passe du modèle per-tâche à un modèle **par jalon** portant :
- `milestone_type` (input/divider/dispatch/agent/tool/evaluator/aggregator/output),
- les nœuds actifs du jalon,
- le **set de liens allumés cumulatif** (backbone accumulé + fan-out courant),
- le contexte sous-tâche (`sub_task_id`, `order_index`),
- le `detail` du modal par type de jalon.

Plus, au niveau run : un modèle `todo` (input + sous-tâches avec état dérivé des jalons QA).

Sources events : `TaskDividedEvent.sub_tasks` (TODO + modal divider), `ToolCalledEvent` (bande tools + modal tool + jalons TOOL), `QAEvaluatedEvent.spec` (modal evaluator), `TaskAggregatedEvent` (modal aggregator). La bande tools collecte les `agent_id`/`tool_name` distincts du run.

**À valider contre de vraies traces vague 1** avant de figer la segmentation des jalons (l'ordre d'émission réel dans `run_chain`/`run_divided_task` détermine le découpage).

## Carte du rework (fichiers)

| Fichier | Changement |
| --- | --- |
| `dashboard/graph_model.py` | Réécriture `build_graph` → modèle jalons cumulatifs + modèle todo + collecte tools. Schémas `GraphStep`/`GraphModel` étendus. **Impacte aussi les case-graphs health (fonction partagée).** |
| `dashboard/static/js/graph.js` | `layout()` 4 bandes ; tier `tools` ; rendu allumage cumulatif (backbone persistant / fan-out transitoire) ; nœuds tools + arêtes `agent→tool`. |
| `dashboard/static/js/modal.js` | Cases `divider`/`aggregator`/`tool` ; evaluator affiche la spec ; afficher `tool_calls_count`. |
| `dashboard/static/js/tabs/sessions.js` | `renderTodo()` : expansion sous-tâches au Divider, rayé au QA-pass, marqué échec au QA-fail. Scrubber : labels par jalon. |
| `dashboard/static/css/*` | Bande tools, états todo sous-items, modals. |

Tests : `build_graph` est pur → couvert en TDD (nouveau modèle jalons, états, conditionnels tools/divider/aggregator) ; le frontend JS reste hors TDD auto (validation navigateur), conformément à V2c.

## Séparations strictes (à ne pas briser)

- Graphe = pipeline réel uniquement : bande tools / nœuds divider/aggregator n'apparaissent que sur events réels (`ToolCalledEvent`/`TaskDividedEvent`), jamais spéculatifs.
- `build_graph` reste **pur** (cœur testable).
- Direction visuelle verrouillée : pas de néon multi-hue, pas de glass, glow uniquement sur live/winner, ember = actif/winning seul, chrome ne compète jamais avec.
- Backbone/fan-out : `agent→evaluator` est fan-out (transitoire), décision verrouillée.

## Open questions (défauts assertés)

- Même tool appelé N fois → N jalons TOOL distincts.
- Position tools = bande tout en haut (périphérie).
- `agent→evaluator` = fan-out transitoire (verrouillé).

## Recommended references (impeccable, pour l'impl)

`animate` (chorégraphie allumage cumulatif + pulses), `layout` (4 tiers + rail), `craft` (build end-to-end).
