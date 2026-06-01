# V3 — Épique A4 — TaskDivider + Aggregateur actif

- **Couche** : `src/aaosa/runtime/` (divider, aggregator) · `src/aaosa/tracing/events.py` · `dashboard/graph_model.py`
- **Statut** : deep-dive terminé → prêt pour plan + exécution
- **Dépendances** : A3 (dure) — requiert `run_chain`, `Task.depends_on`, `Task.parent_task_id`
- **Roadmap** : section V3, épique A4 — "pièce centrale de la thèse le graphe émerge"

---

## Contexte

A3 implémente l'exécution d'une liste de sous-tâches **déjà construite**. A4 ajoute le
composant qui **génère** cette liste (TaskDivider via LLM) et le composant qui **synthétise**
les outputs des sous-tâches (Aggregateur via LLM).

L'émergence : aucune décision de découpe n'est hardcodée. Le graphe d'exécution émerge de
la décision LLM du diviseur — la thèse portfolio concrétisée.

L'« Integrator » V2c était un collecteur passif (aucun LLM, aucune synthèse). L'Aggregateur
A4 est un composant actif : il produit un `Output` réel via un appel LLM.

---

## Ce qui ne change pas

- `run_task`, `run_chain` : comportement inchangé (rétrocompat stricte)
- Tous les tests existants (≥ 615 après A1+B1+A3) : inchangés
- `build_graph` structure de base : nodes/edges/steps restent le même contrat

---

## Décisions

| Question | Décision | Justification |
|---|---|---|
| Emplacement TaskDivider | `src/aaosa/runtime/divider.py` | Concern d'orchestration — pas dans `core/` (claiming) ni `qa/` |
| Emplacement Aggregateur | `src/aaosa/runtime/aggregator.py` | Symétrique au divider |
| TaskDivider = sous-classe Agent ? | **Non** — classe standalone | Pas de `claim()`, pas de `tags_with_elo`. A6 non nécessaire ici. |
| Structured output `required_tags` | `list[TagSpec]` (pas `dict[str, int]`) | OpenAI structured output interdit `additionalProperties` — même raison que `DimensionScore` en V2b |
| `depends_on` dans le structured output | `depends_on_indices: list[int]` (0-based) | Le LLM ne connaît pas les UUID à l'avance. Résolution indice→ID dans `divide()`. |
| Agents passés au divider ? | `divide(task, agents, client, tracer)` | Les tags sont passés comme **vocabulaire de référence non-exhaustif** (pas contrainte fermée). |
| Tags du divider : exhaustifs ? | **Non** — vocabulaire de référence uniquement | Brider le divider aux tags existants l'empêche de décomposer librement. Si un tag inventé ne matche aucun agent → sous-tâche unassigned → signal légitime de gap dans le roster. |
| `agent_id` dans l'Output de l'aggregateur | Sentinel `"aggregator"` | L'aggregateur n'est pas un agent AAOSA — sentinel clair, pas de confusion avec les UUID runtime. |
| Stratégie d'agrégation | **B (LLM Aggregator) primaire, C (synthèse-en-sous-tâche) fallback** | B garantit une synthèse. Si B échoue (exception LLM), fallback = dernier `Output` réussi de la chaîne (qui peut être une sous-tâche de synthèse ajoutée par le divider). |
| Sous-tâches sans succès | `run_divided_task` retourne `DispatchResult(status="unassigned")` | Cohérent avec le reste du runner. Zéro output réussi = tâche non résolue, même le fallback C est inapplicable. |
| Agrégation partielle (certaines sous-tâches échouent) | Agréger uniquement les `Output` réussis | L'aggregateur reçoit la liste des outputs réussis. Les `DispatchResult`/`QAFailure` sont exclus. |
| Cycle dans `depends_on` | Délégué à `run_chain` (lève `ValueError`) | `run_chain` valide déjà. Pas de double validation. |
| Outcome graphe pour tâche divisée | Nouvelle valeur `"divided"` dans `Outcome` | Distingue du flow claiming normal — le frontend sait quel graphe afficher. |

---

## Seams confirmés

| Fichier | État actuel | Ce qui change |
|---|---|---|
| `src/aaosa/runtime/divider.py` | n'existe pas | `TagSpec` · `SubTaskSpec` · `DivisionResult` · `TaskDivider` |
| `src/aaosa/runtime/aggregator.py` | n'existe pas | `TaskAggregator` |
| `src/aaosa/tracing/events.py` | union `ClaimEvent` (10 types) | +`TaskDividedEvent` · +`TaskAggregatedEvent` · mise à jour union |
| `src/aaosa/runtime/runner.py` | `run_task` + `run_chain` (après A3) | +`run_divided_task` |
| `dashboard/graph_model.py` | `NodeType` 6 valeurs · `Outcome` 4 valeurs | +`"divider"` · +`"aggregator"` dans `NodeType` · +`"divided"` dans `Outcome` · `_build_nodes` · `_build_edges` · `_build_step` · `_active_path` |
| `src/aaosa/demo/run_demo.py` | démo atomique uniquement | +un run divisé (divider+aggregator maison) |

---

## Schemas structured output (divider)

```python
# src/aaosa/runtime/divider.py

class TagSpec(BaseModel):
    tag: str
    elo: int

class SubTaskSpec(BaseModel):
    description: str
    required_tags: list[TagSpec]          # list car dict interdit par OpenAI structured output
    depends_on_indices: list[int] = Field(default_factory=list)  # indices 0-based dans sub_tasks

class DivisionResult(BaseModel):
    sub_tasks: list[SubTaskSpec]

    @model_validator(mode="after")
    def at_least_one(self):
        if not self.sub_tasks:
            raise ValueError("sub_tasks cannot be empty")
        return self
```

---

## API TaskDivider

```python
class TaskDivider:
    def __init__(self, system_prompt: str) -> None:
        self.system_prompt = system_prompt

    def divide(
        self,
        task: Task,
        agents: list[Agent],
        client: OpenAI,
        tracer: Tracer | None = None,
    ) -> list[Task]:
        """LLM call → list[Task] avec parent_task_id, order_index, depends_on résolus."""
        # 1. Construire le prompt : description de la tâche + tags disponibles des agents
        # 2. Structured output → DivisionResult
        # 3. Créer les Task avec parent_task_id=task.id, order_index=i
        # 4. Résoudre depends_on_indices → IDs réels
        # 5. Émettre TaskDividedEvent si tracer
```

Prompt divider (construit par `_build_divide_prompt`) :

```
Available agent tags (reference vocabulary — not exhaustive):
  frontend, css, javascript, testing, backend, database, python,
  infrastructure, docker, ci_cd

These tags exist in the current agent roster. Use them when appropriate.
You may use other tags if a sub-task genuinely requires a capability
not covered above — but prefer the existing vocabulary when it fits.
If you use an unknown tag, no agent may be able to claim that sub-task.

Decompose the following task into ordered sub-tasks.
Express dependencies between sub-tasks as 0-based indices into your sub_tasks list.

Task: {task.description}
```

---

## API TaskAggregator

```python
class TaskAggregator:
    def __init__(self, system_prompt: str) -> None:
        self.system_prompt = system_prompt

    def aggregate(
        self,
        parent_task: Task,
        sub_outputs: list[Output],
        client: OpenAI,
        tracer: Tracer | None = None,
    ) -> Output:
        """LLM call → Output synthétisant les sub_outputs.

        Output.task_id = parent_task.id
        Output.agent_id = "aggregator"
        """
```

Prompt aggregateur (construit par `_build_aggregate_prompt`) :

```
Original task: {parent_task.description}

Results from sub-tasks:
[sub-task 1]: {output_1.content}
---
[sub-task 2]: {output_2.content}
...

Synthesize these results into a single coherent response.
```

---

## Nouveaux événements tracer

```python
# src/aaosa/tracing/events.py

class TaskDividedEvent(_BaseEvent):
    type: Literal["task_divided"] = "task_divided"
    task_id: str                    # parent task ID
    sub_task_ids: list[str]         # IDs des sous-tâches générées

class TaskAggregatedEvent(_BaseEvent):
    type: Literal["task_aggregated"] = "task_aggregated"
    task_id: str                    # parent task ID
    sub_task_ids: list[str]
    output_summary: str
    output_content: str
    llm_metadata: LLMMetadata | None = None
```

Mise à jour du `ClaimEvent` union : +`TaskDividedEvent | TaskAggregatedEvent`.

---

## `run_divided_task`

```python
def run_divided_task(
    task: Task,
    agents: list[Agent],
    client: OpenAI,
    divider: "TaskDivider",
    aggregator: "TaskAggregator",
    tracer: Tracer | None = None,
    evaluator: QAEvaluator | None = None,
) -> Output | DispatchResult:
    # 1. divider.divide(task, agents, client, tracer) → sub_tasks
    # 2. run_chain(sub_tasks, agents, client, tracer, evaluator) → sub_results
    # 3. Filtrer les Output réussis : successful = [r for r in sub_results if isinstance(r, Output)]
    # 4. Si successful vide → DispatchResult(status="unassigned", reason="no sub-tasks succeeded")
    # 5. [B] aggregator.aggregate(task, successful, client, tracer) → final_output
    #      Si aggregate() lève une exception :
    #      [C fallback] retourner le dernier Output réussi de la chaîne
    #      (peut être une sous-tâche de synthèse si le divider en a inclus une)
    # 6. return final_output
```

**Fallback C en pratique** : si `aggregate()` échoue (timeout, parse error, API error), la
fonction retourne `successful[-1]` — le dernier output réussi. Si le divider a inclus une
sous-tâche de synthèse en dernière position (dépendant de toutes les autres), cet output est
déjà une synthèse. Sinon c'est le dernier résultat partiel — acceptable comme dégradation
gracieuse plutôt qu'une exception non gérée.

---

## Changements `build_graph`

### NodeType et Outcome

```python
NodeType = Literal["input", "dispatch", "evaluator", "output", "testset", "agent", "divider", "aggregator"]
Outcome = Literal["qa_pass", "qa_fail", "unassigned", "no_qa", "divided"]
```

### `_build_nodes` : détection tâche divisée

Si les events contiennent un `TaskDividedEvent` pour le parent task → ajouter `divider` et
`aggregator` comme nœuds fixes (layer `"center"`), en plus de `input` et `output`.

Les nœuds agent/dispatch/evaluator/testset sont ajoutés uniquement pour les sous-tâches (pas
pour le parent task step) — séparation via `_events_by_task`.

### `_build_edges` : graphe du step parent

Si `divider` dans les nœuds :
```
input → divider
divider → aggregator
aggregator → output
```

### `_active_path` : outcome `"divided"`

```python
if outcome == "divided":
    nodes = ["input", "divider", "aggregator", "output"]
    edges = [
        GraphEdge(from_node="input", to="divider"),
        GraphEdge(from_node="divider", to="aggregator"),
        GraphEdge(from_node="aggregator", to="output"),
    ]
    return nodes, edges
```

### `_build_step` : step parent task

Si le run du parent contient un `TaskDividedEvent` :
- `outcome = "divided"`
- `winner_agent_id = None`
- `dispatch_detail` vide (pas de claiming)
- `output_detail` rempli depuis `TaskAggregatedEvent.output_content/summary/llm_metadata`
- `agents = {}` (pas d'agents au niveau parent)

---

## Stratégie de test (TDD)

**`tests/runtime/test_task_divider.py`** (5 tests) :
- `test_divide_returns_subtasks_with_parent_id` : mock LLM → list[Task], chaque tâche a `parent_task_id = task.id`
- `test_divide_resolves_depends_on_indices` : `depends_on_indices=[0]` sur la 2e sous-tâche → `depends_on=[sub_tasks[0].id]`
- `test_divide_sets_order_index` : `order_index` = 0, 1, 2… dans l'ordre de la liste
- `test_divide_emits_task_divided_event` : tracer reçoit `TaskDividedEvent` avec `sub_task_ids` corrects
- `test_divide_requires_at_least_one_subtask` : `DivisionResult(sub_tasks=[])` → `ValueError`

**`tests/runtime/test_task_aggregator.py`** (4 tests) :
- `test_aggregate_returns_output_with_parent_task_id` : mock LLM → `Output.task_id == parent_task.id`
- `test_aggregate_agent_id_is_sentinel` : `Output.agent_id == "aggregator"`
- `test_aggregate_emits_task_aggregated_event` : tracer reçoit `TaskAggregatedEvent`
- `test_aggregate_llm_metadata_populated` : `Output.llm_metadata` non None

**`tests/runtime/test_run_divided_task.py`** (4 tests) :
- `test_run_divided_task_returns_output` : pipeline complet mocké → `Output`
- `test_run_divided_task_no_successful_subtasks` : tous `DispatchResult` → `DispatchResult(status="unassigned")`
- `test_run_divided_task_aggregates_only_successful` : 1 succès + 1 échec → aggregateur reçoit 1 output
- `test_run_divided_task_tracer_event_order` : `TaskDividedEvent` avant les sous-tâches, `TaskAggregatedEvent` en dernier

**`tests/dashboard/test_build_graph_a4.py`** (3 tests) :
- `test_build_graph_divided_task_has_divider_node` : events avec `TaskDividedEvent` → `"divider"` dans `graph.nodes`
- `test_build_graph_divided_step_outcome_is_divided` : step du parent task → `outcome == "divided"`
- `test_build_graph_divided_active_path` : `active_nodes == ["input", "divider", "aggregator", "output"]`

---

## Critères de done

- [ ] `src/aaosa/runtime/divider.py` : `TagSpec` · `SubTaskSpec` · `DivisionResult` · `TaskDivider.divide`
- [ ] `src/aaosa/runtime/aggregator.py` : `TaskAggregator.aggregate`
- [ ] `events.py` : `TaskDividedEvent` + `TaskAggregatedEvent` + union mise à jour
- [ ] `runner.py` : `run_divided_task` (rétrocompat `run_task`/`run_chain` intacts)
- [ ] `graph_model.py` : `"divider"` + `"aggregator"` + `"divided"` + logic `_build_*` et `_active_path`
- [ ] `run_demo.py` : 1 run divisé demonstrant TaskDivider + Aggregateur
- [ ] 16 nouveaux tests verts
- [ ] Suite complète ≥ 615 + 16 = **631 tests verts**

---

## Questions tranchées ici

1. **Le TaskDivider est-il un Agent ?** Non. Pas de claiming, pas de tags. A6 reste conditionnelle.
2. **`required_tags` en dict dans le structured output ?** Non — `list[TagSpec]` (cf. V2b `DimensionScore`).
3. **`depends_on` : comment le LLM référence les sous-tâches ?** Indices 0-based, résolus en IDs dans `divide()`.
4. **Tags passés au divider : contrainte fermée ?** Non — vocabulaire de référence non-exhaustif. Le divider peut inventer des tags ; une sous-tâche avec un tag inconnu sera unassigned (signal de gap, pas un bug).
5. **Stratégie d'agrégation ?** B (LLM Aggregator) primaire. Fallback C = `successful[-1]` si `aggregate()` lève une exception. Le divider peut inclure une sous-tâche de synthèse pour que le fallback soit déjà une vraie synthèse.
6. **Aggregateur sans output réussi ?** `DispatchResult(status="unassigned")` — cohérent avec le runner.
7. **`agent_id` de l'output aggregateur ?** Sentinel `"aggregator"` — stable, pas un UUID.
8. **Tâche divisée dans le dashboard : step séparé ou dans les nœuds existants ?** Step séparé pour le parent task avec `outcome="divided"` et nœuds `divider`/`aggregator`.
9. **Exécution des sous-tâches en parallèle ?** Non — délégué à `run_chain` (séquentiel en A3). Parallélisation hors scope.
10. **La démo doit créer ses propres divider/aggregator ?** Oui — instanciés dans `run_demo.py` avec des `system_prompt` maison. Le runtime ne hardcode pas de divider.
