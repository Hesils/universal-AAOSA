# D2 — Agrégateur DAG-aware (agrégation par sinks) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** À un fan-in de division, agréger les **sinks** du sous-DAG des frères réussis (un réussi non consommé par un réussi) au lieu de tous les réussis à plat — avec court-circuit à un seul sink, et reflet honnête dans le dashboard.

**Architecture:** `run_chain` change de type de retour (liste → `dict[str, Output]` indexé par id, ordre topologique). Un helper pur `_sinks` calcule les sinks ; `run_with_recovery` branche sur leur nombre (0 → unassigned, 1 → court-circuit, ≥2 → agrégation LLM). Côté dashboard, `build_graph` ne montre l'`aggregator` que si un `TaskAggregatedEvent` réel existe, reconstruit les sinks avec la même règle, et rend un OUTPUT terminal depuis le sink au court-circuit.

**Tech Stack:** Python 3.14, Pydantic 2.13, pytest 9.0.3, `.venv\Scripts\python -m pytest`. Imports absolus (`from aaosa...`). TDD subagent-driven.

**Spec source:** `docs/superpowers/specs/2026-06-04-d2-aggregateur-dag-aware-design.md`

---

## File Structure

- `src/aaosa/runtime/runner.py` — ajout `_sinks` (pur), changement type de retour `run_chain`, rewire fan-in de `run_with_recovery`.
- `src/aaosa/runtime/aggregator.py` — prompt resserré (« résultats complémentaires »).
- `dashboard/graph_model.py` — `_build_nodes`/`_build_edges` keyent l'aggregator sur `TaskAggregatedEvent` ; helper `_graph_sinks` ; `_milestones_divided` multi-sink (sinks → aggregator, total/collected = nb sinks) et single-sink (OUTPUT terminal depuis le sink).
- `tests/runtime/test_run_chain.py` — assertions liste → dict.
- `tests/runtime/test_run_with_recovery.py` — single-sink court-circuit, multi-sink sur sinks, fallback sur sinks.
- `tests/runtime/test_task_aggregator.py` — prompt complémentaire.
- `tests/dashboard/test_build_graph_milestones.py` — fixture `_divided_events` rendue indépendante (2 vrais sinks) ; 2 tests node/edge mis à jour.
- `tests/dashboard/test_build_graph_d2.py` — **nouveau** : single-sink court-circuit + multi-sink avec intermédiaire consommé.

---

### Task 1: Helper pur `_sinks` (runtime)

Calcule les sinks d'un fan-in : une sous-tâche réussie non consommée par une sous-tâche réussie. Pure, sans LLM, sans effet de bord. Préalable au rewire de `run_with_recovery` (Task 2).

**Files:**
- Modify: `src/aaosa/runtime/runner.py` (ajout d'une fonction, après `_topological_order`)
- Test: `tests/runtime/test_sinks.py` (create)

- [ ] **Step 1: Write the failing test**

Créer `tests/runtime/test_sinks.py` :

```python
from aaosa.runtime.runner import _sinks
from aaosa.schemas.output import LLMMetadata, Output
from aaosa.schemas.task import Task


def _task(description, depends_on=None) -> Task:
    return Task(description=description, required_tags={"python": 30}, depends_on=depends_on or [])


def _out(task_id) -> Output:
    return Output(
        task_id=task_id, agent_id="x", content=f"c-{task_id}",
        llm_metadata=LLMMetadata(model_name="m", tokens_in=1, tokens_out=1, latency_ms=1.0),
    )


def _by_id(*tasks) -> dict[str, Output]:
    return {t.id: _out(t.id) for t in tasks}


class TestSinks:
    def test_chain_last_is_only_sink(self):
        # investigate -> analyze -> fix (tous réussis) => sink = {fix}
        a = _task("investigate")
        b = _task("analyze", depends_on=[a.id])
        c = _task("fix", depends_on=[b.id])
        sinks = _sinks([a, b, c], _by_id(a, b, c))
        assert [o.task_id for o in sinks] == [c.id]

    def test_parallel_all_are_sinks(self):
        # parse_logs, check_db indépendants (tous réussis) => sinks = {parse_logs, check_db}
        a = _task("parse_logs")
        b = _task("check_db")
        sinks = _sinks([a, b], _by_id(a, b))
        assert {o.task_id for o in sinks} == {a.id, b.id}

    def test_convergent_diamond_single_sink(self):
        # A->B->D, A->C->D (tous réussis) => sink = {D}
        a = _task("A")
        b = _task("B", depends_on=[a.id])
        c = _task("C", depends_on=[a.id])
        d = _task("D", depends_on=[b.id, c.id])
        sinks = _sinks([a, b, c, d], _by_id(a, b, c, d))
        assert [o.task_id for o in sinks] == [d.id]

    def test_failed_merge_resurfaces_inputs_as_sinks(self):
        # A->B->D, A->C->D mais D a ÉCHOUÉ (absent du dict) => sinks = {B, C}
        a = _task("A")
        b = _task("B", depends_on=[a.id])
        c = _task("C", depends_on=[a.id])
        d = _task("D", depends_on=[b.id, c.id])
        outputs = _by_id(a, b, c)  # D échoué : pas dans outputs
        sinks = _sinks([a, b, c, d], outputs)
        assert {o.task_id for o in sinks} == {b.id, c.id}

    def test_consumed_by_failed_sibling_is_still_sink(self):
        # S réussi, T (qui dépend de S) a échoué => S non consommé => S est un sink
        s = _task("S")
        t = _task("T", depends_on=[s.id])
        sinks = _sinks([s, t], _by_id(s))  # T absent
        assert [o.task_id for o in sinks] == [s.id]

    def test_consumed_by_succeeded_sibling_is_not_sink(self):
        s = _task("S")
        t = _task("T", depends_on=[s.id])
        sinks = _sinks([s, t], _by_id(s, t))
        assert [o.task_id for o in sinks] == [t.id]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_sinks.py -v`
Expected: FAIL with `ImportError: cannot import name '_sinks'`

- [ ] **Step 3: Write minimal implementation**

Dans `src/aaosa/runtime/runner.py`, ajouter cette fonction juste après `_topological_order` (après la ligne `return order`, avant `def run_chain`) :

```python
def _sinks(sub_tasks: list[Task], outputs_by_id: dict[str, Output]) -> list[Output]:
    """Sinks du sous-DAG des frères réussis : un réussi non consommé par un réussi (§2).

    Un sink est un résultat terminal « lâche » qui doit être fusionné ; un réussi
    consommé par un réussi est déjà replié dans son consommateur (required_outputs).
    Ordre = ordre de sub_tasks (ordre du divider). Pur, pas d'appel LLM."""
    succeeded = set(outputs_by_id)
    consumed = {
        dep
        for t in sub_tasks if t.id in succeeded
        for dep in t.depends_on if dep in succeeded
    }
    return [outputs_by_id[t.id] for t in sub_tasks if t.id in succeeded and t.id not in consumed]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_sinks.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
rtk git add tests/runtime/test_sinks.py src/aaosa/runtime/runner.py
rtk git commit -m "feat(d2): helper pur _sinks (sinks du sous-DAG des freres reussis)"
```

---

### Task 2: `run_chain` → `dict[str, Output]` + rewire fan-in de `run_with_recovery` (cœur couplé)

Changement couplé volontaire (comme la Task 7 de D1) : changer le type de retour de `run_chain` casse immédiatement son unique appelant `run_with_recovery`. Les deux changent ensemble, et leurs deux fichiers de tests sont mis à jour dans le même commit pour ne jamais laisser d'état rouge.

**Files:**
- Modify: `src/aaosa/runtime/runner.py:165-191` (`run_chain`), `src/aaosa/runtime/runner.py:274-286` (bloc fan-in de `run_with_recovery`)
- Test: `tests/runtime/test_run_chain.py`, `tests/runtime/test_run_with_recovery.py`

- [ ] **Step 1: Write the failing tests — `run_chain` retourne un dict**

Dans `tests/runtime/test_run_chain.py`, **remplacer** les méthodes `test_no_deps`, `test_execution_error_is_contained` et `test_dependency_failed_skips` par celles-ci (les autres méthodes de la classe restent inchangées) :

```python
    def test_no_deps(self):
        a = make_agent()
        t1, t2, t3 = make_task("A"), make_task("B"), make_task("C")
        recorded = {}
        with patch.object(Agent, "claim", _claim_for(a)):
            with patch.object(Agent, "execute", _recording_execute(recorded)):
                outputs = run_chain([t1, t2, t3], _ctx_for_chain([a]), 1)
        assert list(outputs.keys()) == [t1.id, t2.id, t3.id]
        assert all(isinstance(o, Output) for o in outputs.values())

    def test_execution_error_is_contained(self):
        # Une sous-tâche dont l'exécution lève (ex: MAX_TOOL_ROUNDS) ne tue pas la chaîne :
        # elle est absente du dict, les indépendantes réussissent, ses dépendants sont sautés.
        a = make_agent()
        t1 = make_task("A")                       # lèvera
        t2 = make_task("B")                       # indépendante -> réussit
        t3 = make_task("C", depends_on=[t1.id])   # dépend de la tâche en échec

        def exploding_execute(self, task, client, tracer=None):
            if task.description == "A":
                raise RuntimeError("max tool rounds exceeded")
            return Output(
                task_id=task.id, agent_id=self.id, content="ok",
                llm_metadata=LLMMetadata(model_name="m", tokens_in=1, tokens_out=1, latency_ms=1.0),
            )

        with patch.object(Agent, "claim", _claim_for(a)):
            with patch.object(Agent, "execute", exploding_execute):
                outputs = run_chain([t1, t2, t3], _ctx_for_chain([a]), 1)

        assert t1.id not in outputs                       # execution_failed -> absent
        assert isinstance(outputs[t2.id], Output)         # indépendante réussie
        assert t3.id not in outputs                       # dépendance non résolue -> sautée

    def test_dependency_failed_skips(self):
        a = make_agent()
        t1 = make_task("A")
        # B requires a tag the agent lacks -> unassigned -> no output
        t_b = Task(description="B", required_tags={"rust": 99})
        t_c = make_task("C", depends_on=[t_b.id])
        recorded = {}
        with patch.object(Agent, "claim", _claim_for(a)):
            with patch.object(Agent, "execute", _recording_execute(recorded)):
                outputs = run_chain([t1, t_b, t_c], _ctx_for_chain([a]), 1)
        assert isinstance(outputs[t1.id], Output)
        assert t_b.id not in outputs    # unassigned
        assert t_c.id not in outputs    # dépendance échouée -> jamais exécutée
        assert t_c.id not in recorded
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_run_chain.py -v`
Expected: FAIL — `run_chain` renvoie encore une liste (`AttributeError: 'list' object has no attribute 'keys'` / `KeyError`).

- [ ] **Step 3: Rewrite `run_chain` to return a dict**

Dans `src/aaosa/runtime/runner.py`, **remplacer entièrement** `run_chain` (lignes 165-191) par :

```python
def run_chain(sub_tasks: list[Task], ctx: RunContext, depth: int) -> dict[str, Output]:
    """Exécute des sous-tâches ordonnées par leur DAG de dépendances (Kahn) et renvoie
    les outputs RÉUSSIS indexés par id de tâche (ordre d'insertion = ordre topologique).

    Recovery-aware (D1) : l'exécuteur par nœud est `run_with_recovery`. required_outputs
    des deps réussies injectés, input non muté (model_copy). Les échecs ne sont pas dans
    le retour (déjà contenus/tracés à l'exécution) ; un dépendant dont une dep manque est
    simplement sauté. Interne à la récursion : seul `run_with_recovery` l'appelle (D2)."""
    order = _topological_order(sub_tasks)
    outputs: dict[str, Output] = {}

    for task in order:
        unmet = [dep for dep in task.depends_on if dep not in outputs]
        if unmet:
            continue
        resolved = [outputs[dep] for dep in task.depends_on]
        task_to_run = task.model_copy(update={"required_outputs": resolved})
        result = run_with_recovery(task_to_run, ctx, depth)
        if isinstance(result, Output):
            outputs[task.id] = result

    return outputs
```

- [ ] **Step 4: Run `run_chain` tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_run_chain.py -v`
Expected: PASS (toutes — y compris cycle/unknown-dependency/required-outputs inchangées).

- [ ] **Step 5: Write the failing tests — fan-in de `run_with_recovery` sur les sinks**

Dans `tests/runtime/test_run_with_recovery.py` :

(a) **Ajouter** ces helpers de module, après `_two_subtask_division` (≈ ligne 73) :

```python
def _two_independent_division():
    return DivisionResult(sub_tasks=[
        SubTaskSpec(description="s1"),
        SubTaskSpec(description="s2"),
    ])


def _router(task, agents, client, tracer=None, evaluator=None):
    """run_task simulé : la racine (description "t") reste unassigned pour déclencher la
    division ; chaque sous-tâche réussit avec un Output portant SON id (pour que _sinks
    fonctionne sur les vrais ids générés par build_sub_tasks)."""
    if task.description == "t":
        return DispatchResult(status="unassigned", agent_id=None, reason="no claim")
    return make_output(task.id, f"out-{task.description}")


class _SpyAggregator:
    def __init__(self):
        self.called_with = None

    def aggregate(self, parent_task, sub_outputs, client, tracer=None):
        self.called_with = list(sub_outputs)
        return make_output(parent_task.id, "agg")
```

(b) **Remplacer** `test_unassigned_triggers_division_then_aggregates`, `test_no_successful_subtasks_returns_unassigned` et `test_aggregator_exception_falls_back_to_last_output` par :

```python
    def test_single_sink_short_circuits_without_aggregating(self):
        # division en chaîne (s2 dépend de s1) -> 1 seul sink (s2) -> court-circuit
        agg = _SpyAggregator()
        ctx = _ctx(_StaticDivider(_two_subtask_division()), aggregator=agg)
        task = Task(description="t", required_tags={"python": 30})
        with patch("aaosa.runtime.runner.run_task", side_effect=_router):
            result = run_with_recovery(task, ctx)
        assert isinstance(result, Output)
        assert result.content == "out-s2"      # le sink, renvoyé tel quel
        assert agg.called_with is None         # aucun appel LLM d'agrégation

    def test_multi_sink_aggregates_sinks_only(self):
        # division en branches indépendantes -> 2 sinks -> agrégation sur les sinks
        agg = _SpyAggregator()
        ctx = _ctx(_StaticDivider(_two_independent_division()), aggregator=agg)
        task = Task(description="t", required_tags={"python": 30})
        with patch("aaosa.runtime.runner.run_task", side_effect=_router):
            result = run_with_recovery(task, ctx)
        assert result.content == "agg"
        assert {o.content for o in agg.called_with} == {"out-s1", "out-s2"}

    def test_no_successful_subtasks_returns_unassigned(self):
        ctx = _ctx(_StaticDivider(_two_subtask_division()))
        task = Task(description="t", required_tags={"python": 30})
        unassigned = DispatchResult(status="unassigned", agent_id=None, reason="no claim")
        with patch("aaosa.runtime.runner.run_task", return_value=unassigned):
            with patch("aaosa.runtime.runner.run_chain", return_value={}):
                result = run_with_recovery(task, ctx)
        assert result.status == "unassigned"
        assert result.reason == "no sub-tasks recovered"

    def test_aggregator_exception_falls_back_to_last_sink(self):
        ctx = _ctx(_StaticDivider(_two_independent_division()), aggregator=_ExplodingAggregator())
        task = Task(description="t", required_tags={"python": 30})
        with patch("aaosa.runtime.runner.run_task", side_effect=_router):
            result = run_with_recovery(task, ctx)
        assert result.content == "out-s2"   # fallback sur sinks[-1]
```

- [ ] **Step 6: Run tests to verify the new fan-in tests fail**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_run_with_recovery.py -v`
Expected: FAIL — `run_with_recovery` agrège encore tous les réussis (`successful`), donc le court-circuit n'existe pas et `agg.called_with` n'est pas `None`.

- [ ] **Step 7: Rewire the fan-in of `run_with_recovery`**

Dans `src/aaosa/runtime/runner.py`, **remplacer** le bloc final de `run_with_recovery` (lignes 274-286, de `sub_results = run_chain(...)` jusqu'à `return successful[-1]`) par :

```python
    outputs_by_id = run_chain(sub_tasks, ctx, depth + 1)
    if not outputs_by_id:
        return DispatchResult(
            status="unassigned",
            agent_id=None,
            reason="no sub-tasks recovered",
        )

    sinks = _sinks(sub_tasks, outputs_by_id)
    if len(sinks) == 1:
        return sinks[0]   # court-circuit : un seul résultat terminal, rien à synthétiser

    try:
        return ctx.aggregator.aggregate(task, sinks, ctx.client, ctx.tracer)
    except Exception:
        return sinks[-1]
```

- [ ] **Step 8: Run the full runtime suite to verify green**

Run: `.venv\Scripts\python -m pytest tests/runtime/ -v`
Expected: PASS (run_chain, run_with_recovery, sinks, et le reste runtime).

- [ ] **Step 9: Commit**

```bash
rtk git add src/aaosa/runtime/runner.py tests/runtime/test_run_chain.py tests/runtime/test_run_with_recovery.py
rtk git commit -m "feat(d2): run_chain -> dict, fan-in sur les sinks (court-circuit a 1 sink)"
```

---

### Task 3: Prompt d'agrégation resserré (« résultats complémentaires »)

L'agrégateur reçoit désormais des **sinks** (des pairs complémentaires, pas une chaîne). Le prompt doit le dire : chaque résultat couvre une partie de la tâche, produire une réponse unique qui les couvre tous. Signature `aggregate` inchangée.

**Files:**
- Modify: `src/aaosa/runtime/aggregator.py:24-32` (`_build_aggregate_prompt`)
- Test: `tests/runtime/test_task_aggregator.py`

- [ ] **Step 1: Write the failing test**

Dans `tests/runtime/test_task_aggregator.py`, ajouter à la classe `TestTaskAggregator` :

```python
    def test_prompt_frames_results_as_complementary(self):
        captured = {}

        def create(**kwargs):
            captured["user"] = kwargs["messages"][-1]["content"]
            return SimpleNamespace(
                model="gpt-4o-mini",
                choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
                usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
            )

        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        agg = TaskAggregator(system_prompt="You synthesize.")
        agg.aggregate(make_parent(), [make_output("a", "A"), make_output("b", "B")], client)
        assert "complementary" in captured["user"].lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_task_aggregator.py::TestTaskAggregator::test_prompt_frames_results_as_complementary -v`
Expected: FAIL — le prompt dit « Results from sub-tasks », pas « complementary ».

- [ ] **Step 3: Tighten the prompt**

Dans `src/aaosa/runtime/aggregator.py`, **remplacer** `_build_aggregate_prompt` (lignes 24-32) par :

```python
    def _build_aggregate_prompt(self, parent_task: Task, sub_outputs: list[Output]) -> str:
        parts = [
            f"Original task: {parent_task.description}",
            "",
            "The results below are complementary: each covers a distinct part of the "
            "original task. They are peers, not a sequence.",
            "",
            "Complementary results:",
        ]
        for i, out in enumerate(sub_outputs, start=1):
            if i > 1:
                parts.append("---")
            parts.append(f"[result {i}]: {out.content}")
        parts.append("")
        parts.append("Produce a single coherent response that covers all of them.")
        return "\n".join(parts)
```

- [ ] **Step 4: Run the aggregator tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_task_aggregator.py -v`
Expected: PASS (5 tests — les 4 existantes + la nouvelle).

- [ ] **Step 5: Commit**

```bash
rtk git add src/aaosa/runtime/aggregator.py tests/runtime/test_task_aggregator.py
rtk git commit -m "feat(d2): prompt agregateur resserre (sinks = resultats complementaires)"
```

---

### Task 4: `build_graph` — l'`aggregator` n'apparaît que sur `TaskAggregatedEvent` réel

Au court-circuit (single-sink), le runtime n'émet aucun `TaskAggregatedEvent`. Le graphe doit alors **ne pas** montrer de nœud/arête `aggregator` (séparation V3 §9 : le graphe ne montre que le pipeline réel). On key l'aggregator sur la présence de l'event, pas sur la simple division.

**Files:**
- Modify: `dashboard/graph_model.py:244-264` (`_build_nodes`), `dashboard/graph_model.py:267-293` (`_build_edges`)
- Test: `tests/dashboard/test_build_graph_milestones.py:45-49` et `:60-72`

- [ ] **Step 1: Update the failing node/edge tests**

Dans `tests/dashboard/test_build_graph_milestones.py`, **remplacer** `test_divider_aggregator_nodes_only_when_divided` (lignes 45-49) par :

```python
    def test_divider_node_when_divided_aggregator_only_when_aggregated(self):
        assert "divider" not in {n.id for n in _build_nodes([])}
        # divisé mais sans agrégation (court-circuit single-sink) -> divider, PAS d'aggregator
        divided = [TaskDividedEvent(session_id=SID, task_id="p", sub_tasks=[DividedSubTask(id="s1", description="x")])]
        ids = {n.id for n in _build_nodes(divided)}
        assert "divider" in ids and "aggregator" not in ids
        # divisé + agrégé -> les deux nœuds
        agg = divided + [TaskAggregatedEvent(session_id=SID, task_id="p", sub_task_ids=["s1"],
                                             output_summary="o", output_content="o")]
        ids2 = {n.id for n in _build_nodes(agg)}
        assert "divider" in ids2 and "aggregator" in ids2
```

Et **remplacer** `test_divider_backbone_edges` (lignes 60-72) par les deux tests suivants :

```python
    def test_divider_backbone_edges_single_sink(self):
        # divisé sans event d'agrégation -> backbone evaluator->output, aucun aggregator
        divided = [TaskDividedEvent(session_id=SID, task_id="p", sub_tasks=[DividedSubTask(id="s1", description="x")])]
        nodes = _build_nodes(divided)
        edges = _build_edges(nodes, divided)
        pairs = {(e.from_node, e.to) for e in edges}
        assert ("input", "divider") in pairs
        assert ("divider", "dispatch") in pairs
        assert ("evaluator", "output") in pairs
        assert ("evaluator", "aggregator") not in pairs
        assert ("input", "dispatch") not in pairs

    def test_divider_backbone_edges_multi_sink(self):
        events = [
            TaskDividedEvent(session_id=SID, task_id="p", sub_tasks=[DividedSubTask(id="s1", description="x")]),
            TaskAggregatedEvent(session_id=SID, task_id="p", sub_task_ids=["s1"], output_summary="o", output_content="o"),
        ]
        nodes = _build_nodes(events)
        edges = _build_edges(nodes, events)
        pairs = {(e.from_node, e.to) for e in edges}
        assert ("evaluator", "aggregator") in pairs
        assert ("aggregator", "output") in pairs
        assert ("divider", "aggregator") not in pairs
```

Note : `TaskAggregatedEvent` et `_build_edges` sont déjà importés dans ce fichier (utilisés plus bas) — vérifier la présence des imports en tête de fichier, et les ajouter seulement s'ils manquent.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_build_graph_milestones.py -k "divider" -v`
Expected: FAIL — `_build_nodes` ajoute encore l'aggregator dès qu'il y a un `TaskDividedEvent`, et `_build_edges` câble `evaluator->aggregator->output` sans event d'agrégation.

- [ ] **Step 3: Key nodes on `TaskAggregatedEvent`**

Dans `dashboard/graph_model.py`, dans `_build_nodes`, **remplacer** le bloc (lignes 254-256) :

```python
    if any(isinstance(e, TaskDividedEvent) for e in events):
        nodes.append(GraphNode(id="divider", layer="center", type="divider", label="Divider"))
        nodes.append(GraphNode(id="aggregator", layer="center", type="aggregator", label="Aggregator"))
```

par :

```python
    if any(isinstance(e, TaskDividedEvent) for e in events):
        nodes.append(GraphNode(id="divider", layer="center", type="divider", label="Divider"))
        # l'aggregator n'apparaît que s'il y a eu une vraie agrégation (≥2 sinks).
        # Single-sink (court-circuit) -> aucun TaskAggregatedEvent -> pas de nœud aggregator.
        if any(isinstance(e, TaskAggregatedEvent) for e in events):
            nodes.append(GraphNode(id="aggregator", layer="center", type="aggregator", label="Aggregator"))
```

- [ ] **Step 4: Key edges on the aggregator node presence**

Dans `dashboard/graph_model.py`, dans `_build_edges`, **remplacer** le corps (lignes 274-293, de `agent_ids = ...` jusqu'au `return edges`) par :

```python
    agent_ids = [n.id for n in nodes if n.type == "agent"]
    divided = any(n.id == "divider" for n in nodes)
    aggregated = any(n.id == "aggregator" for n in nodes)
    edges: list[GraphEdge] = []
    if divided:
        edges.append(GraphEdge(from_node="input", to="divider"))
        edges.append(GraphEdge(from_node="divider", to="dispatch"))
    else:
        edges.append(GraphEdge(from_node="input", to="dispatch"))
    edges += [GraphEdge(from_node="dispatch", to=aid) for aid in agent_ids]
    edges += [GraphEdge(from_node=aid, to="evaluator") for aid in agent_ids]
    for aid, tname in _distinct_tools(events):
        edges.append(GraphEdge(from_node=aid, to=_tool_node_id(tname)))
    if aggregated:
        edges.append(GraphEdge(from_node="evaluator", to="aggregator"))
        edges.append(GraphEdge(from_node="aggregator", to="output"))
    else:
        edges.append(GraphEdge(from_node="evaluator", to="output"))
    if _has_qa_fail(events):
        edges.append(GraphEdge(from_node="evaluator", to="testset"))
    return edges
```

(Mettre à jour aussi la docstring de `_build_edges` : « Divisé sans agrégation : ...→evaluator→output ; divisé+agrégé : ...→evaluator→aggregator→output. »)

- [ ] **Step 5: Run the dashboard suite to verify nodes/edges green**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_build_graph_milestones.py tests/dashboard/test_build_graph_a4.py -v`
Expected: PASS — les tests node/edge mis à jour passent ; les fixtures portant un `TaskAggregatedEvent` (a4, `_divided_events`) gardent leur aggregator.

- [ ] **Step 6: Commit**

```bash
rtk git add dashboard/graph_model.py tests/dashboard/test_build_graph_milestones.py
rtk git commit -m "feat(d2): graphe montre l'aggregator seulement sur TaskAggregatedEvent reel"
```

---

### Task 5: `build_graph` — sinks au fan-in (multi-sink) + OUTPUT terminal (single-sink)

Reconstruit les sinks côté dashboard (même règle qu'en §2) : seuls les sinks nourrissent l'aggregator et comptent dans `total`/`collected` ; au court-circuit single-sink, le jalon OUTPUT terminal vient du sink (pas d'aggregator). On rend aussi le fixture partagé `_divided_events` **indépendant** (2 vrais sinks) pour que ses assertions d'agrégation restent valides sous D2.

**Files:**
- Modify: `dashboard/graph_model.py` (ajout `_graph_sinks` ; `_milestones_divided`)
- Test: `tests/dashboard/test_build_graph_milestones.py:183-203` (fixture `_divided_events`)
- Test: `tests/dashboard/test_build_graph_d2.py` (create)

- [ ] **Step 1: Make the shared fixture genuinely multi-sink**

Dans `tests/dashboard/test_build_graph_milestones.py`, dans `_divided_events` (ligne 189), **rendre sub2 indépendante** en retirant sa dépendance — remplacer la ligne :

```python
            DividedSubTask(id=S2, description="fix", depends_on=[S1], required_tags={"python": 60}),
```

par :

```python
            DividedSubTask(id=S2, description="fix", depends_on=[], required_tags={"python": 60}),
```

(Les deux sous-tâches deviennent des branches parallèles → 2 sinks → l'agrégation reste réelle. Toutes les assertions existantes — séquence de jalons, `collected` 1→2, `total==2`, `sub_task_ids==["sub1","sub2"]`, tags — restent vraies sous D2.)

- [ ] **Step 2: Write the failing D2 tests**

Créer `tests/dashboard/test_build_graph_d2.py` :

```python
from aaosa.tracing.events import (
    DividedSubTask,
    DispatchedEvent,
    ExecutedEvent,
    Phase1FilteredEvent,
    QAEvaluatedEvent,
    TaskAggregatedEvent,
    TaskDividedEvent,
)
from aaosa.tracing.store import SessionMeta, SessionTaskRecord
from dashboard.graph_model import build_graph

SID, P = "sess-d2", "parent"


def _meta():
    return SessionMeta(
        session_id=SID, started_at="2026-01-01T00:00:00Z", ended_at="2026-01-01T00:01:00Z",
        tasks=[SessionTaskRecord(id=P, description="incident", winner_agent_id=None, outcome="divided", required_tags={})],
        agent_ids=["ag"],
    )


def _sub(task_id, content, success=True):
    return [
        Phase1FilteredEvent(session_id=SID, task_id=task_id, agent_id="ag", passed=True, fit_score=0.9),
        DispatchedEvent(session_id=SID, task_id=task_id, agent_id="ag", reason="sole claimer"),
        ExecutedEvent(session_id=SID, task_id=task_id, agent_id="ag", output_summary=content, output_content=content),
        QAEvaluatedEvent(session_id=SID, task_id=task_id, agent_id="ag", success=success, score=1.0 if success else 0.0, reason="r"),
    ]


def _single_sink_chain_events():
    """investigate -> fix (fix dépend d'investigate), tous deux réussis, AUCUNE agrégation
    (court-circuit : un seul sink = fix)."""
    S1, S2 = "s1", "s2"
    return [
        TaskDividedEvent(session_id=SID, task_id=P, sub_tasks=[
            DividedSubTask(id=S1, description="investigate", depends_on=[]),
            DividedSubTask(id=S2, description="fix", depends_on=[S1]),
        ]),
        *_sub(S1, "c1"),
        *_sub(S2, "c2"),
        # pas de TaskAggregatedEvent
    ]


def _multi_sink_with_intermediate_events():
    """investigate -> analyze (analyze dépend d'investigate) + check (indépendant).
    Sinks = {analyze, check} ; investigate est consommé, donc PAS un sink."""
    S1, S2, S3 = "s1", "s2", "s3"
    return [
        TaskDividedEvent(session_id=SID, task_id=P, sub_tasks=[
            DividedSubTask(id=S1, description="investigate", depends_on=[]),
            DividedSubTask(id=S2, description="analyze", depends_on=[S1]),
            DividedSubTask(id=S3, description="check", depends_on=[]),
        ]),
        *_sub(S1, "c1"),
        *_sub(S2, "c2"),
        *_sub(S3, "c3"),
        TaskAggregatedEvent(session_id=SID, task_id=P, sub_task_ids=["s2", "s3"],
                            output_summary="final", output_content="final report"),
    ]


class TestSingleSinkCourtCircuit:
    def test_no_aggregator_node(self):
        graph = build_graph(_single_sink_chain_events(), _meta())
        assert "aggregator" not in {n.id for n in graph.nodes}

    def test_no_aggregator_milestone_terminal_is_output(self):
        graph = build_graph(_single_sink_chain_events(), _meta())
        types = [s.milestone_type for s in graph.steps]
        assert "aggregator" not in types
        assert types[-1] == "output"

    def test_output_comes_from_the_sink(self):
        graph = build_graph(_single_sink_chain_events(), _meta())
        out = graph.steps[-1]
        assert out.detail.output.output_content == "c2"   # fix = le sink
        pairs = {(e.from_node, e.to) for e in out.active_edges}
        assert ("evaluator", "output") in pairs


class TestMultiSinkWithConsumedIntermediate:
    def test_consumed_intermediate_does_not_feed_aggregator(self):
        graph = build_graph(_multi_sink_with_intermediate_events(), _meta())
        ev_by_sub = {s.sub_task_id: s for s in graph.steps if s.milestone_type == "evaluator"}
        # investigate (s1) est consommé par analyze (s2) -> pas un sink -> n'allume pas l'aggregator
        assert "aggregator" not in ev_by_sub["s1"].active_nodes
        # analyze (s2) et check (s3) sont des sinks -> allument l'aggregator
        assert "aggregator" in ev_by_sub["s2"].active_nodes
        assert "aggregator" in ev_by_sub["s3"].active_nodes

    def test_total_and_collected_count_sinks(self):
        graph = build_graph(_multi_sink_with_intermediate_events(), _meta())
        agg = next(s for s in graph.steps if s.milestone_type == "aggregator")
        assert agg.detail.aggregator.total == 2          # 2 sinks, pas 3 sous-tâches
        assert agg.detail.aggregator.collected == 2
        assert agg.detail.aggregator.sub_task_ids == ["s2", "s3"]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_build_graph_d2.py -v`
Expected: FAIL — single-sink : pas de jalon OUTPUT terminal (le code actuel saute aggregator ET output quand `aggregated_ev is None`). Multi-sink : `total==3` et l'intermédiaire allume l'aggregator (le code compte chaque qa_pass).

- [ ] **Step 4: Add `_graph_sinks` helper**

Dans `dashboard/graph_model.py`, ajouter cette fonction juste avant `_milestones_divided` (avant la ligne `def _milestones_divided`) :

```python
def _graph_sinks(divided_ev, sub_runs) -> list[str]:
    """Sinks reconstruits côté dashboard, même règle qu'en runtime `_sinks` (§2) :
    une sous-tâche qa_pass non consommée par une sous-tâche qa_pass. Pur."""
    passed = {r.task_id for r in sub_runs if r.outcome == "qa_pass"}
    consumed = {
        dep
        for st in divided_ev.sub_tasks if st.id in passed
        for dep in st.depends_on if dep in passed
    }
    return [st.id for st in divided_ev.sub_tasks if st.id in passed and st.id not in consumed]
```

- [ ] **Step 5: Multi-sink — only sinks feed the aggregator; total/collected count sinks**

Dans `dashboard/graph_model.py`, dans `_milestones_divided` :

(a) Après la ligne `acc = _EdgeAccumulator()` (≈ ligne 557), ajouter :

```python
    sink_ids = set(_graph_sinks(divided_ev, sub_runs))
```

(b) **Remplacer** l'initialisation du compteur (lignes 580-581) :

```python
    total = len(sub_runs)
    collected = 0
```

par :

```python
    total = len(sink_ids)   # le récit de collecte porte sur les sinks, pas toutes les sous-tâches
    collected = 0
```

(c) Dans la branche evaluator qa_pass (lignes 617-624), **remplacer** :

```python
            elif run.outcome == "qa_pass":
                # sortie validée → collectée par l'aggregator (qui s'allume, arête transitoire).
                # shallow copy : on surcharge .aggregator sans muter le detail partagé des frères.
                collected += 1
                nodes_q.append("aggregator")
                fanq.append(("evaluator", "aggregator"))
                ev_detail = detail.model_copy()
                ev_detail.aggregator = AggregatorDetail(aggregated=False, collected=collected, total=total)
```

par :

```python
            elif run.outcome == "qa_pass" and aggregated_ev is not None and run.task_id in sink_ids:
                # seul un SINK validé est collecté par l'aggregator (les intermédiaires consommés
                # sont déjà repliés dans leur dépendant). shallow copy : surcharge .aggregator
                # sans muter le detail partagé des frères.
                collected += 1
                nodes_q.append("aggregator")
                fanq.append(("evaluator", "aggregator"))
                ev_detail = detail.model_copy()
                ev_detail.aggregator = AggregatorDetail(aggregated=False, collected=collected, total=total)
```

- [ ] **Step 6: Single-sink — OUTPUT terminal from the sink (no aggregator)**

Dans `dashboard/graph_model.py`, dans `_milestones_divided`, le bloc final `if aggregated_ev is not None:` (lignes 631-649) gère l'agrégation. **Ajouter** juste après ce bloc (avant `return steps`) la branche court-circuit :

```python
    elif len(sink_ids) == 1:
        # court-circuit D2 : un seul sink, aucune agrégation. OUTPUT terminal depuis le sink
        # (l'output réel de l'agent du sink) — image honnête : aucune synthèse n'a eu lieu.
        sink_run = next((r for r in sub_runs if r.task_id in sink_ids), None)
        if sink_run is not None and sink_run.executed is not None:
            sink_input = InputDetail(
                task_id=sink_run.task_id, description=_sub_desc(divided_ev, sink_run.task_id),
                required_tags=_sub_tags(divided_ev, sink_run.task_id),
            )
            out_detail = _scope_detail(sink_input, sink_run)
            acc.add_backbone("evaluator", "output")
            steps.append(GraphStep(
                milestone_type="output", label="OUTPUT", active_nodes=["output"],
                active_edges=acc.snapshot([]), winner_agent_id=sink_run.winner_id,
                outcome="divided", detail=out_detail, todo=td("output", None),
            ))
```

- [ ] **Step 7: Run the D2 dashboard tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_build_graph_d2.py -v`
Expected: PASS (5 tests).

- [ ] **Step 8: Run the full dashboard suite for non-regression**

Run: `.venv\Scripts\python -m pytest tests/dashboard/ -v`
Expected: PASS — y compris `_divided_events` (désormais 2 sinks indépendants), a4, et les états fail/unassigned.

- [ ] **Step 9: Commit**

```bash
rtk git add dashboard/graph_model.py tests/dashboard/test_build_graph_milestones.py tests/dashboard/test_build_graph_d2.py
rtk git commit -m "feat(d2): build_graph agrege par sinks + OUTPUT terminal au court-circuit"
```

---

### Task 6: Full suite + documentation

Vérifier la non-régression globale et refléter D2 dans `CLAUDE.md` (pratique F7 de D1 : la doc évolue après chaque session d'implémentation).

**Files:**
- Modify: `CLAUDE.md` (section « Séparations strictes V3 » + état courant)

- [ ] **Step 1: Run the entire test suite**

Run: `.venv\Scripts\python -m pytest -q`
Expected: PASS — 747 (D1) + nouveaux tests D2, zéro régression. Noter le total exact.

- [ ] **Step 2: Update `CLAUDE.md`**

Dans `CLAUDE.md`, sous « Séparations strictes V3 à ne pas briser », ajouter une puce D2 :

```markdown
- **Agrégation par sinks (D2)** : à un fan-in, `run_chain` renvoie `dict[str, Output]` (réussis par id, ordre topologique) ; le helper pur `_sinks(sub_tasks, outputs_by_id)` calcule les sinks (un réussi non consommé par un réussi). `run_with_recovery` branche : 0 réussi → `unassigned` · **1 sink → court-circuit** (renvoie l'`Output` du sink tel quel, garde son `agent_id` réel, aucun appel LLM, aucun `TaskAggregatedEvent`) · ≥2 sinks → `aggregator.aggregate(task, sinks, ...)`, fallback `sinks[-1]` sur exception. Le sentinel `agent_id="aggregator"` reste réservé à l'agrégateur réel. Côté dashboard, `build_graph` ne montre l'`aggregator` que sur un `TaskAggregatedEvent` réel ; au court-circuit il rend un OUTPUT terminal depuis le sink ; `total`/`collected` comptent les sinks (règle de sink dupliquée runtime + `_graph_sinks`, duplication assumée vs couplage data).
```

Mettre aussi à jour la ligne d'« État courant » V3 pour mentionner D2 implémenté (nb de tests, branche `feat/v3-d2`).

- [ ] **Step 3: Commit**

```bash
rtk git add CLAUDE.md
rtk git commit -m "docs(d2): separations strictes agregation par sinks + etat courant"
```

---

## Notes d'exécution

- **Branche** : `feat/v3-d2` (déjà créée, porte la spec `7062c45`). Tous les commits y vont. Merge `--no-ff` sur master sur demande de Quentin (master = commit-sur-demande).
- **Heads-up démo (spec §6, hors scope)** : `run_demo_v3` divise en chaîne se terminant par une synthèse → un seul sink → court-circuitera. Le « showpiece » d'agrégation de 6 outputs disparaît — c'est **correct** (la chaîne était double-comptée). Aucune action ici ; la vraie agrégation relève de la C-démo (branches parallèles). Ne pas « réparer » le démo en forçant une agrégation.
- **`run_chain` est interne** : seul `run_with_recovery` l'appelle (vérifié — aucun autre site dans `src/`). Le changement de type de retour est donc contenu.

## Self-Review

- **Couverture spec** : §2 sinks → Task 1 (+ les 4 formes + consommé-par-échec). §3 fan-in (0/1/≥2) → Task 2. §4.1 `run_chain` dict + `_sinks` + branchement → Tasks 1-2. §4.2 prompt complémentaire + `sub_task_ids` = sinks → Task 3 (sub_task_ids automatique via `sub_outputs`). §5 dashboard multi-sink (total/collected = sinks) + single-sink (OUTPUT terminal, pas d'aggregator) + détection par présence d'event → Tasks 4-5. §8 tests → couverts (sinks purs, fan-in 1/≥2/0, run_chain dict, build_graph single/multi). §9 séparations (court-circuit garde l'agent_id réel ; aggregator node seulement sur event réel) → Tasks 2 et 4.
- **Placeholders** : aucun — tout step de code montre le code complet.
- **Cohérence des types** : `_sinks(sub_tasks: list[Task], outputs_by_id: dict[str, Output]) -> list[Output]` et `_graph_sinks(divided_ev, sub_runs) -> list[str]` (ids) ; `run_chain(...) -> dict[str, Output]` ; `run_with_recovery` consomme `_sinks` (Outputs) et `build_graph` consomme `_graph_sinks` (ids comparés à `sub_task_id`/`run.task_id`). Le `_router` de test renvoie un `Output` portant le `task.id` réel pour que `_sinks` mappe les vrais ids. Cohérent.
