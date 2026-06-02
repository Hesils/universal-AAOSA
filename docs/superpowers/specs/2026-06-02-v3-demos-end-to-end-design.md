# V3 — Observabilité end-to-end : vague 1 (pipeline + events)

Date : 2026-06-02
Statut : design validé, prêt pour plan d'implémentation
Périmètre : **vague 1 uniquement** (runtime + events émis). La vague 2 (adaptation
frontend) sera brainstormée séparément, sur la base des vraies traces produites par
la vague 1. La vision frontend est consignée en annexe pour justifier chaque event.

## Objectif

Démontrer le chemin critique V3 de bout en bout, avec un LLM réel, à partir d'un
input utilisateur riche, et émettre exactement les events dont le futur dashboard a
besoin pour rendre :

- le graphe cumulatif d'un run divisé (chaîne émergente + tool calls + agrégation) ;
- la TODO dynamique d'achèvement de l'input ;
- la spec d'évaluation auto-générée (B1) au nœud Evaluator ;
- la boucle d'auto-amélioration (B2 triage → B3 task-spec → re-triage → health check).

Deux livrables exécutables : `run_demo_v3.py` (runtime) et `run_health_check_v3.py`
(nature B). Les démos V2b existantes restent intactes comme point de comparaison.

## Découpage en deux vagues

- **Vague 1 (ce spec)** : runtime + events. Produit des traces complètes
  (divided + tools + B1 + boucle B2/B3) lisibles via `print_timeline` et persistées.
- **Vague 2 (spec ultérieur)** : réécriture de `build_graph` en modèle cumulatif par
  jalons, couche tools, panneau TODO, modals divider/aggregator, affichage spec B1,
  modèle d'allurage. Conçue à partir des traces réelles de la vague 1.

## Décisions verrouillées

- **Placement** : nouveaux scripts `run_demo_v3.py` / `run_health_check_v3.py`.
- **Tools** : stubbés déterministes (reproductibilité).
- **Health check** : boucle complète `échec → B2 → B3 → re-triage → health check`.
- **Fix runner** : inclus, en TDD (prérequis tool calls observables).
- **Cas health check** : curés avec `wrong_output` canned.
- **B1** : fix de la dette + `build_llm_spec` intégré. La spec générée est par
  (sous-)tâche, produite à la volée par un evaluator paresseux.
- **Génération de spec par (sous-)tâche** : via `AdaptiveSpecEvaluator` qui construit
  la spec dans `evaluate(task, output)` — satisfait le Protocol `QAEvaluator`, zéro
  changement de signature dans `run_task`/`run_chain`/`run_divided_task`.
- **Trace de la spec B1** : champ optionnel `spec` sur `QAEvaluatedEvent`, alimenté
  via `QAResult.spec_used`.
- **`run_demo_v3`** : un seul run, l'incident divisé.
- **`run_divided_task` API** : inchangé. L'identité/description des sous-tâches vient
  du `TaskDividedEvent` enrichi, pas des SessionTaskRecord.

## Découvertes (gaps révélés)

### Gap A5 — tracer non propagé

`run_task` (`runtime/runner.py:40`) appelle `winner.execute(task, client)` **sans
`tracer`**. La boucle tool-use s'exécute mais `ToolCalledEvent` n'est jamais émis →
les tool calls sont invisibles en trace. Fix chirurgical, rétrocompatible :
`winner.execute(task, client, tracer)` (`execute` a déjà `tracer=None` par défaut et
n'émet que si un tracer est fourni).

### Dette B1 — client non injecté dans les critères

`llm_check` (`criteria.py:98`) lit `params.get("client")` et lève si absent.
`SpecEvaluator.evaluate` (`spec_evaluator.py:31,47`) passe `c.params` **tel quel** →
toute spec contenant `llm_check` lève en runtime réel. Le `client` n'est pas dans la
spec sérialisée (non sérialisable, par design).

## Composants (vague 1)

### 1. Fix `runtime/runner.py`

`winner.execute(task, client)` → `winner.execute(task, client, tracer)`.
TDD : test RED vérifiant l'émission d'un `ToolCalledEvent` via `run_task` quand
l'agent dispatché porte des tools.

### 2. Fix dette B1 — `qa/spec_evaluator.py`

- `evaluate` : injecter `self.client` dans les params passés aux critères, dans la
  boucle des gates **et** des critères scorés —
  `get_criterion(c.name)(task, output, {**c.params, "client": self.client})`.
- Garde du constructeur : exiger un client si un judge **ou** un critère `llm_check`
  est présent —
  `needs_client = spec.judge is not None or any(c.name == "llm_check" for c in spec.criteria)`.
- Alimenter `QAResult.spec_used = self.spec` dans le retour (pour la trace B1).

TDD : une spec avec `llm_check` évaluée avec un client mocké ne lève plus et produit
un `QAResult` ; sans client, le constructeur lève.

### 3. `qa/protocol.py` — `QAResult.spec_used`

Ajouter `spec_used: EvaluatorSpec | None = None` (import `from aaosa.qa.spec import
EvaluatorSpec` ; pas de cycle : `spec.py` n'importe pas `protocol.py`). Champ
optionnel → rétrocompat des `QAResult` existants.

### 4. `AdaptiveSpecEvaluator` — `qa/spec_evaluator.py`

Evaluator paresseux par tâche, satisfait le Protocol `QAEvaluator` :

```python
class AdaptiveSpecEvaluator:
    def __init__(self, client: OpenAI):
        self.client = client

    def evaluate(self, task: Task, output: Output) -> QAResult:
        spec = build_llm_spec(task, self.client)            # B1, par tâche
        return SpecEvaluator(spec, client=self.client).evaluate(task, output)
```

- `evaluate(task, output)` reçoit déjà la tâche → spec construite pour la bonne
  tâche, à la volée, lors du run. `SpecEvaluator` (corrigé) alimente
  `QAResult.spec_used`, que `run_task` recopiera sur `QAEvaluatedEvent`.
- Import `build_llm_spec` depuis `adaptive.py` (pas de cycle : `adaptive.py`
  n'importe pas `spec_evaluator.py`).
- Séparation V2b respectée : le runtime injecte un évaluateur, ne génère pas la spec
  lui-même.

TDD : `evaluate` appelle `build_llm_spec` (mocké) puis délègue à `SpecEvaluator` ;
le `QAResult` porte `spec_used`.

### 5. `tracing/events.py` — events enrichis

- `QAEvaluatedEvent` : ajouter `spec: EvaluatorSpec | None = None` (import
  `EvaluatorSpec`). `run_task` le remplit depuis `qa_result.spec_used`.
- `TaskDividedEvent` : remplacer `sub_task_ids: list[str]` par
  `sub_tasks: list[DividedSubTask]` où

  ```python
  class DividedSubTask(BaseModel):
      model_config = ConfigDict(extra="forbid")
      id: str
      description: str
      depends_on: list[str] = Field(default_factory=list)
  ```

  Porte description + dépendances pour la TODO, le nœud Divider et l'ordering.
  `TaskAggregatedEvent` reste inchangé.

Impacts : `divider.divide` (`runtime/divider.py:94`) construit les `DividedSubTask`
depuis les `Task` qu'il vient de créer (id/description/depends_on déjà disponibles) ;
`run_task` alimente `QAEvaluatedEvent.spec`. Tests existants sur `TaskDividedEvent` /
divider à mettre à jour (changement de champ).

### 6. `demo/tools.py` (nouveau) — toolbox stubbée

Les `ToolDef` portent des callables non sérialisables → attachés programmatiquement.
4 `ToolDef` à `fn` figée mais réaliste (retournent toujours `str`) :

- `read_file(path)` — contenu figé des fichiers de l'incident, générique sinon.
- `grep_codebase(pattern)` — matches figés.
- `run_tests(path)` — sortie pytest figée.
- `explain_query_plan(sql)` — plan EXPLAIN figé (full table scans).

`attach_tools(agents)` : mutation en place de `agent.tools`, sous-ensemble par **nom** :
Backend = les 4 ; Frontend = `read_file`, `grep_codebase` ; Fullstack = `read_file`,
`run_tests` ; DevOps = `read_file`.

### 7. `demo/run_demo_v3.py` (nouveau) — démo runtime

Un seul run : l'incident de production en `metadata["context"]` (log + snippets).
Ex. *« Le endpoint de checkout renvoie des 500 intermittents sous charge. On suspecte
l'auth middleware et une requête SQL lente du reporting. Diagnostique, corrige, ajoute
un test de non-régression. »*

1. `load_agents` → `attach_tools(agents)`.
2. `evaluator = AdaptiveSpecEvaluator(client)`.
3. `run_divided_task(task, agents, client, divider, aggregator, tracer, evaluator)` :
   divider fait émerger la chaîne ordonnée → `run_chain` résout `depends_on` →
   chaque sous-tâche dispatch sur un agent outillé (boucle tool-use A5) → chaque
   sous-tâche QA-évaluée par une spec LLM dédiée (B1) → aggregator synthétise (A4).
4. `print_timeline` → persistance `runs/` (`save_agent_registry`, `save_session`,
   snapshot ELO). La démo enregistre le **parent** divisé comme `SessionTaskRecord`
   (les sous-tâches viennent du `TaskDividedEvent` enrichi côté frontend).

### 8. `demo/run_health_check_v3.py` (nouveau) — démo nature B

Test set seedé avec des cas `unattributed`, `origin="runtime_failure"`, `wrong_output`
canned. Specs par cas générées via `build_llm_spec(task, client)` (peuvent contenir
`llm_check`, exécutées par le `SpecEvaluator` corrigé).

Orchestration côté caller (zéro couplage B2/B3) :

1. Affiche les attributions initiales (toutes `unattributed`).
2. `triage_unattributed` (B2) → classifie. Delta affiché.
3. `fix_task_spec_cases` (B3) → réécrit `task.description` des cas `task_spec`, reset
   à `unattributed`, conserve `task.id`. Delta affiché.
4. `triage_unattributed` (re-triage). Delta affiché.
5. `active_cases` → `run_health_check(agents, set, client, n_runs=3, tracer)`.
6. Rapport, `graduate`, `save_health_check`.

À vérifier en implémentation : `run_health_check` construit bien son `SpecEvaluator`
avec le `client` (sinon les specs `llm_check` lèveraient malgré le fix). Présumé OK
(le judge V2b l'exige déjà) ; à confirmer.

## Hors scope (vague 1)

- **A2** (2e domaine) : on reste software.
- **Tools sur le vrai filesystem** : écarté.
- **Cas health check générés par un vrai `run_task` en échec** : écarté (flaky).
- **Tout le frontend** : vague 2.

## Critères vérifiables

- `run_demo_v3.py` produit dans la trace : ≥1 `TaskDividedEvent` enrichi
  (sub_tasks avec descriptions), une chaîne ordonnée exécutée, ≥1 `ToolCalledEvent`,
  ≥1 `QAEvaluatedEvent` portant une `spec`, un `TaskAggregatedEvent` final ; session
  persistée dans `runs/`.
- `run_health_check_v3.py` : au moins un cas suit
  `unattributed → task_spec → (corrigé) unattributed → agent/...` ; rapport généré
  et sauvegardé.
- Fix runner : `ToolCalledEvent` émis via `run_task` (test dédié).
- Fix B1 : spec `llm_check` évaluée sans lever (avec client) ; garde lève sans client.
- Suite complète verte : 669 existants + nouveaux (runner, B1, AdaptiveSpecEvaluator,
  tools, events enrichis, divider mis à jour). Pas de régression sur les démos V2b ni
  sur `build_graph` (le changement `TaskDividedEvent` impacte ses tests — à ajuster).

## Découpage en unités

| Unité | Fichier | Rôle | Dépend de |
| --- | --- | --- | --- |
| Fix runner | `runtime/runner.py` | tracer → execute + spec → QAEvaluatedEvent | events |
| Fix dette B1 | `qa/spec_evaluator.py` | inject client + garde + spec_used | criteria, spec |
| QAResult.spec_used | `qa/protocol.py` | porte la spec utilisée | spec |
| AdaptiveSpecEvaluator | `qa/spec_evaluator.py` | spec LLM paresseuse par tâche | adaptive, spec_evaluator |
| Events enrichis | `tracing/events.py` | QAEvaluatedEvent.spec, TaskDividedEvent.sub_tasks | spec |
| Divider | `runtime/divider.py` | émet DividedSubTask | events |
| Toolbox | `demo/tools.py` | ToolDef stubbés + attach_tools | core/tool, core/agent |
| Démo runtime | `demo/run_demo_v3.py` | incident divisé + tools + B1 | tout ci-dessus |
| Démo health check | `demo/run_health_check_v3.py` | boucle B2→B3→B2→health check | triage, task_spec_generator, health_check, build_llm_spec |

Les scripts démo sont des points d'entrée (`__main__`), non testés au-delà de
l'import ; le TDD porte sur runner, B1, AdaptiveSpecEvaluator, events, divider, tools.

## Annexe — Vision frontend (vague 2, consignée)

Justifie les events de la vague 1. Non implémenté ici.

### Modèle de graphe : jalons cumulatifs

Un « step » de la timeline = un **jalon** qui fait avancer l'état du graphe, en
cumulatif. Jalons curés : **Input, Divider, Dispatch, Agent, ToolCall, Evaluator,
Aggregator, Output**. Les events Phase1/Phase2 par agent sont regroupés dans le jalon
**Dispatch** (son modal résume candidats + justifications phase1/phase2). Le scrubber
rejoue la construction progressive d'**un run unique** (parent + sous-tâches groupés
via `TaskDividedEvent`). Remplace le modèle actuel « un step = une tâche, chemin
pré-allumé ».

### Couche tools

4e tier, le plus périphérique, sous les agents (les tools n'interagissent qu'avec les
agents). **1 nœud par tool distinct**, relié à chaque agent qui le possède
(`read_file` = un seul nœud partagé). Données : `ToolCalledEvent`
(agent_id, tool_name, arguments, result, latency_ms).

### Modèle d'allumage

- **Nœuds** : allumés uniquement quand actifs.
- **Liens backbone (root↔trunk)** — peu nombreux (`input↔divider↔dispatch`,
  `evaluator↔aggregator↔output`) : cumulatifs et persistants (squelette de pipeline).
- **Liens fan-out** (`dispatch↔agent`, `agent↔evaluator`, `agent↔tool`) — nombreux :
  transitoires. Seul le lien de la sous-tâche / de l'appel en cours est allumé ;
  éteint à la résolution (lue via `QAEvaluatedEvent(task_id, success)`), le dispatch
  suivant allume le lien du nouveau winner.

### Panneau Tasks = TODO dynamique

Step 1 : input utilisateur seul (racine). Après le Divider : toutes les sous-tâches
en sous-todos (depuis `TaskDividedEvent.sub_tasks` : description + ordre via
`depends_on`). Rayées à la **réussite QA** (`QAEvaluatedEvent.success`) ; échecs QA
marqués distinctement, pas rayés.

### Nœud Evaluator

Affiche la **spec générée complète** (critères, descriptions `llm_check`, poids)
depuis `QAEvaluatedEvent.spec`, en plus des `criteria_results` / score / judge.

### Gaps frontend connexes (à traiter vague 2)

- `build_graph` ignore `ToolCalledEvent` → à collecter (couche tools + détail modal).
- `modal.js` n'affiche pas `tool_calls_count` ni de case `divider`/`aggregator`.
- Parcours B2/B3 non persisté → si on veut le rendre observable, prévoir un artefact
  (log de triage / test_sets intermédiaires) côté health check.
