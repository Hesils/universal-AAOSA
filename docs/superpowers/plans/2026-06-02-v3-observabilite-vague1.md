# V3 Observabilité end-to-end — Vague 1 (pipeline + events) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Émettre les events et fournir le runtime nécessaires pour démontrer le chemin critique V3 (chaîne divisée émergente + tool calls + spec d'évaluation auto-générée par sous-tâche + boucle d'auto-amélioration B2/B3), via deux scripts de démo exécutables avec un LLM réel.

**Architecture:** TDD strict, changements rétrocompatibles. On ferme deux gaps d'intégration (tracer non propagé à `execute` ; client non injecté dans les critères `llm_check`), on ajoute un evaluator paresseux qui génère la spec par tâche (`AdaptiveSpecEvaluator`), on enrichit deux events (`QAEvaluatedEvent.spec`, `TaskDividedEvent.sub_tasks`), et on livre une toolbox stubbée + deux scripts démo. Le frontend (vague 2) n'est PAS touché.

**Tech Stack:** Python 3.14, Pydantic 2.13, OpenAI SDK 2.38, pytest 9 (+pytest-asyncio). Tests via `.venv\Scripts\python -m pytest`. Mocks par `types.SimpleNamespace` (jamais d'appel LLM réel en test).

**Spec de référence:** `docs/superpowers/specs/2026-06-02-v3-demos-end-to-end-design.md`

**Convention de commit:** terminer chaque message par
`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`

---

## Task 1: `QAResult.spec_used`

Porte la spec effectivement utilisée par l'évaluateur, pour la tracer ensuite sur `QAEvaluatedEvent`.

**Files:**
- Modify: `src/aaosa/qa/protocol.py`
- Test: `tests/qa/test_protocol.py`

- [ ] **Step 1: Write the failing test**

Ajouter dans `tests/qa/test_protocol.py` :

```python
def test_qaresult_spec_used_defaults_none():
    from aaosa.qa.protocol import QAResult
    r = QAResult(
        task_id="t1", agent_id="a1", success=True, score=1.0,
        reason="ok", criteria_results={"non_empty": True},
    )
    assert r.spec_used is None


def test_qaresult_accepts_spec_used():
    from aaosa.qa.protocol import QAResult
    from aaosa.qa.spec import CriterionSpec, EvaluatorSpec
    spec = EvaluatorSpec(criteria=[CriterionSpec(name="non_empty", gate=True)])
    r = QAResult(
        task_id="t1", agent_id="a1", success=True, score=1.0,
        reason="ok", criteria_results={"non_empty": True}, spec_used=spec,
    )
    assert r.spec_used == spec
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/qa/test_protocol.py::test_qaresult_accepts_spec_used -v`
Expected: FAIL — `ValidationError` (extra field `spec_used` forbidden).

- [ ] **Step 3: Add the field**

Dans `src/aaosa/qa/protocol.py`, ajouter l'import et le champ :

```python
from aaosa.qa.spec import EvaluatorSpec
```

et dans `class QAResult`, après `judge: JudgeBreakdown | None = None` :

```python
    spec_used: EvaluatorSpec | None = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/qa/test_protocol.py -v`
Expected: PASS (tous).

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/qa/protocol.py tests/qa/test_protocol.py
git commit -m "feat(v3): QAResult.spec_used pour tracer la spec utilisee"
```

---

## Task 2: `QAEvaluatedEvent.spec`

Champ optionnel transportant la spec générée vers la trace (affiché au nœud Evaluator en vague 2).

**Files:**
- Modify: `src/aaosa/tracing/events.py`
- Test: `tests/tracing/test_events_v2.py`

- [ ] **Step 1: Write the failing test**

Ajouter dans `tests/tracing/test_events_v2.py` :

```python
def test_qa_evaluated_event_carries_spec():
    from aaosa.tracing.events import QAEvaluatedEvent
    from aaosa.qa.spec import CriterionSpec, EvaluatorSpec
    spec = EvaluatorSpec(criteria=[CriterionSpec(name="non_empty", gate=True)])
    ev = QAEvaluatedEvent(
        session_id="s", task_id="t", agent_id="a",
        success=True, score=1.0, reason="ok",
        criteria_results={"non_empty": True}, spec=spec,
    )
    roundtrip = QAEvaluatedEvent.model_validate_json(ev.model_dump_json())
    assert roundtrip.spec == spec


def test_qa_evaluated_event_spec_defaults_none():
    from aaosa.tracing.events import QAEvaluatedEvent
    ev = QAEvaluatedEvent(
        session_id="s", task_id="t", agent_id="a",
        success=True, score=1.0, reason="ok", criteria_results={},
    )
    assert ev.spec is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/tracing/test_events_v2.py::test_qa_evaluated_event_carries_spec -v`
Expected: FAIL — `ValidationError` (extra field `spec`).

- [ ] **Step 3: Add the field**

Dans `src/aaosa/tracing/events.py`, ajouter l'import en tête (après `from aaosa.schemas.output import LLMMetadata`) :

```python
from aaosa.qa.spec import EvaluatorSpec
```

et dans `class QAEvaluatedEvent`, après `judge: JudgeBreakdown | None = None` :

```python
    spec: EvaluatorSpec | None = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/tracing/test_events_v2.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/tracing/events.py tests/tracing/test_events_v2.py
git commit -m "feat(v3): QAEvaluatedEvent.spec (trace de la spec generee)"
```

---

## Task 3: `TaskDividedEvent` → `sub_tasks` (DividedSubTask)

Remplace `sub_task_ids: list[str]` par une liste structurée portant description + dépendances (pour la TODO et le nœud Divider en vague 2). Migration : 5 sites.

**Files:**
- Modify: `src/aaosa/tracing/events.py`
- Modify: `src/aaosa/runtime/divider.py:90-99`
- Modify: `src/aaosa/tracing/formatter.py:79`
- Test: `tests/runtime/test_task_divider.py:106` (mise à jour)
- Test: `tests/dashboard/test_build_graph_a4.py:19` (mise à jour)

- [ ] **Step 1: Write the failing test (divider émet sub_tasks)**

Remplacer le corps de `test_divide_emits_task_divided_event` dans `tests/runtime/test_task_divider.py` (assertion ligne 106) par :

```python
    def test_divide_emits_task_divided_event(self):
        task = make_task()
        result = DivisionResult(
            sub_tasks=[
                SubTaskSpec(description="a", required_tags=[TagSpec(tag="python", elo=60)]),
                SubTaskSpec(
                    description="b",
                    required_tags=[TagSpec(tag="python", elo=60)],
                    depends_on_indices=[0],
                ),
            ]
        )
        tracer = Tracer(session_id="sess-1")
        divider = TaskDivider(system_prompt="You split tasks.")
        sub_tasks = divider.divide(task, [make_agent()], _client_returning(result), tracer)

        events = [e for e in tracer.events if isinstance(e, TaskDividedEvent)]
        assert len(events) == 1
        emitted = events[0].sub_tasks
        assert [s.id for s in emitted] == [st.id for st in sub_tasks]
        assert [s.description for s in emitted] == ["a", "b"]
        assert emitted[1].depends_on == [sub_tasks[0].id]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_task_divider.py::TestTaskDivider::test_divide_emits_task_divided_event -v`
Expected: FAIL — `AttributeError: 'TaskDividedEvent' object has no attribute 'sub_tasks'`.

- [ ] **Step 3: Update the event schema**

Dans `src/aaosa/tracing/events.py`, ajouter la classe `DividedSubTask` (après les imports, avant `Phase1FilteredEvent`) :

```python
class DividedSubTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    description: str
    depends_on: list[str] = Field(default_factory=list)
```

et remplacer dans `class TaskDividedEvent` la ligne `sub_task_ids: list[str]` par :

```python
    sub_tasks: list[DividedSubTask]
```

(Ne PAS toucher `TaskAggregatedEvent.sub_task_ids`.)

- [ ] **Step 4: Update the divider emission**

Dans `src/aaosa/runtime/divider.py`, importer `DividedSubTask` :

```python
from aaosa.tracing.events import DividedSubTask, TaskDividedEvent
```

et remplacer le bloc d'émission (lignes ~93-98) par :

```python
        if tracer is not None:
            tracer.emit(TaskDividedEvent(
                session_id=tracer.session_id,
                task_id=task.id,
                sub_tasks=[
                    DividedSubTask(id=st.id, description=st.description, depends_on=list(st.depends_on))
                    for st in sub_tasks
                ],
            ))
        return sub_tasks
```

- [ ] **Step 5: Update the formatter**

Dans `src/aaosa/tracing/formatter.py:79`, remplacer :

```python
            line = f"[{time_str}] DIVIDED -> {len(event.sub_task_ids)} sub-tasks"
```

par :

```python
            line = f"[{time_str}] DIVIDED -> {len(event.sub_tasks)} sub-tasks"
```

(La ligne 85 AGGREGATED utilise `TaskAggregatedEvent.sub_task_ids` — ne pas y toucher.)

- [ ] **Step 6: Update the build_graph A4 test fixture**

Dans `tests/dashboard/test_build_graph_a4.py`, ajouter l'import de `DividedSubTask` à la ligne d'import des events, et remplacer à la ligne 19 :

```python
        TaskDividedEvent(session_id=SID, task_id=PARENT, sub_task_ids=[SUB1]),
```

par :

```python
        TaskDividedEvent(session_id=SID, task_id=PARENT,
                         sub_tasks=[DividedSubTask(id=SUB1, description="sub", depends_on=[])]),
```

(Ne PAS modifier la ligne 25 — c'est un `TaskAggregatedEvent`.)

- [ ] **Step 7: Run the impacted suites**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_task_divider.py tests/runtime/test_run_divided_task.py tests/tracing/test_formatter.py tests/dashboard/test_build_graph_a4.py -v`
Expected: PASS (tous).

- [ ] **Step 8: Run the full suite (no regression)**

Run: `.venv\Scripts\python -m pytest -q`
Expected: PASS. Si un test échoue sur `sub_task_ids`, vérifier qu'il concernait bien `TaskDividedEvent` (et non `TaskAggregatedEvent`) et l'adapter au champ `sub_tasks`.

- [ ] **Step 9: Commit**

```bash
git add src/aaosa/tracing/events.py src/aaosa/runtime/divider.py src/aaosa/tracing/formatter.py tests/runtime/test_task_divider.py tests/dashboard/test_build_graph_a4.py
git commit -m "feat(v3): TaskDividedEvent.sub_tasks (description + depends_on) pour la TODO/divider"
```

---

## Task 4: Fix dette B1 — injection client + garde + spec_used

`SpecEvaluator.evaluate` doit injecter `self.client` dans les params des critères (sinon `llm_check` lève), exiger un client si `llm_check` est présent, et renseigner `QAResult.spec_used`.

**Files:**
- Modify: `src/aaosa/qa/spec_evaluator.py`
- Test: `tests/qa/test_spec_evaluator.py`

- [ ] **Step 1: Write the failing tests**

Ajouter dans `tests/qa/test_spec_evaluator.py` (le module importe déjà `CriterionSpec, EvaluatorSpec`) :

```python
from types import SimpleNamespace


class _LLMCheckClient:
    """Mock le micro-appel de llm_check : parse() -> parsed{score, reason}."""
    def __init__(self, score: float, reason: str = "ok"):
        self._parsed = SimpleNamespace(score=score, reason=reason)
        self.beta = self
        self.chat = self
        self.completions = self

    def parse(self, **kwargs):
        message = SimpleNamespace(parsed=self._parsed)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class TestLLMCheckIntegration:
    def test_llm_check_client_injected(self):
        # Sans le fix, llm_check lève "requires a 'client' in params".
        spec = EvaluatorSpec(
            criteria=[
                CriterionSpec(name="non_empty", gate=True),
                CriterionSpec(name="llm_check",
                              params={"description": "must mention indexing"}, weight=1.0),
            ],
            success_threshold=0.5,
        )
        ev = SpecEvaluator(spec, client=_LLMCheckClient(score=0.9))
        r = ev.evaluate(make_task(), make_output("use a DB index on the token column"))
        assert r.criteria_results["llm_check"] is True
        assert r.success is True

    def test_llm_check_without_client_raises_at_construction(self):
        spec = EvaluatorSpec(
            criteria=[
                CriterionSpec(name="non_empty", gate=True),
                CriterionSpec(name="llm_check", params={"description": "x"}, weight=1.0),
            ],
        )
        with pytest.raises(ValueError, match="client"):
            SpecEvaluator(spec, client=None)

    def test_spec_used_populated(self):
        spec = EvaluatorSpec(criteria=[CriterionSpec(name="non_empty", gate=True)],
                             success_threshold=0.5)
        r = SpecEvaluator(spec).evaluate(make_task(), make_output("hello"))
        assert r.spec_used == spec
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/qa/test_spec_evaluator.py::TestLLMCheckIntegration -v`
Expected: FAIL — `test_llm_check_client_injected` lève `ValueError: llm_check requires a 'client'` ; `test_llm_check_without_client_raises_at_construction` ne lève pas ; `test_spec_used_populated` voit `spec_used is None`.

- [ ] **Step 3: Implement the fix**

Dans `src/aaosa/qa/spec_evaluator.py`, classe `SpecEvaluator` :

a) Étendre le garde du constructeur. Remplacer :

```python
        if spec.judge is not None and client is None:
            raise ValueError("spec has a judge but no client was provided")
```

par :

```python
        needs_client = spec.judge is not None or any(
            c.name == "llm_check" for c in spec.criteria
        )
        if needs_client and client is None:
            raise ValueError("spec needs a client (judge or llm_check) but none was provided")
```

b) Injecter le client dans les params, aux deux endroits où un critère est appelé. Remplacer chacune des deux occurrences de :

```python
            outcome = get_criterion(c.name)(task, output, c.params)
```

par :

```python
            outcome = get_criterion(c.name)(task, output, {**c.params, "client": self.client})
```

c) Renseigner `spec_used` dans le `QAResult` final (verdict, étape 4). Ajouter le champ au `return QAResult(...)` final :

```python
        return QAResult(
            task_id=task.id, agent_id=output.agent_id,
            success=final >= self.spec.success_threshold,
            score=final, reason=reason, criteria_results=criteria_results,
            judge=judge_breakdown,
            spec_used=self.spec,
        )
```

(Ne pas modifier le `QAResult` de court-circuit du gate échoué : un gate échoué retourne tôt sans `spec_used` — acceptable, le nœud Evaluator n'affiche la spec que sur une évaluation complète. Si on veut la spec même sur gate fail, ajouter aussi `spec_used=self.spec` au `return` du gate.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/qa/test_spec_evaluator.py -v`
Expected: PASS (anciens + nouveaux).

- [ ] **Step 5: Run the full suite**

Run: `.venv\Scripts\python -m pytest -q`
Expected: PASS. Vérifier en particulier `tests/qa/test_health_check.py` (utilise `SpecEvaluator` via `run_health_check`) : la nouvelle injection `client` est inerte sur les critères déterministes.

- [ ] **Step 6: Commit**

```bash
git add src/aaosa/qa/spec_evaluator.py tests/qa/test_spec_evaluator.py
git commit -m "fix(v3-b1): SpecEvaluator injecte le client (llm_check) + spec_used + garde"
```

---

## Task 5: `AdaptiveSpecEvaluator` (spec LLM paresseuse par tâche)

Evaluator satisfaisant le Protocol `QAEvaluator` qui génère la spec via `build_llm_spec` dans `evaluate`, puis délègue à `SpecEvaluator`. Aucune signature de runner ne change.

**Files:**
- Modify: `src/aaosa/qa/spec_evaluator.py`
- Test: `tests/qa/test_spec_evaluator.py`

- [ ] **Step 1: Write the failing tests**

Ajouter dans `tests/qa/test_spec_evaluator.py` :

```python
import aaosa.qa.spec_evaluator as se_module
from aaosa.qa.spec_evaluator import AdaptiveSpecEvaluator


class TestAdaptiveSpecEvaluator:
    def test_satisfies_protocol(self):
        assert isinstance(AdaptiveSpecEvaluator(client=object()), QAEvaluator)

    def test_evaluate_builds_spec_per_task_and_delegates(self, monkeypatch):
        known = EvaluatorSpec(criteria=[CriterionSpec(name="non_empty", gate=True)],
                              success_threshold=0.5)
        calls = {"n": 0}
        def fake_build(task, client):
            calls["n"] += 1
            return known
        monkeypatch.setattr(se_module, "build_llm_spec", fake_build)

        ev = AdaptiveSpecEvaluator(client=object())
        r = ev.evaluate(make_task(), make_output("hello world"))
        assert calls["n"] == 1
        assert r.success is True
        assert r.spec_used == known
```

(`QAEvaluator` et `se_module` sont déjà importés en tête du fichier — sinon les imports ci-dessus les ajoutent.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/qa/test_spec_evaluator.py::TestAdaptiveSpecEvaluator -v`
Expected: FAIL — `ImportError: cannot import name 'AdaptiveSpecEvaluator'`.

- [ ] **Step 3: Implement AdaptiveSpecEvaluator**

Dans `src/aaosa/qa/spec_evaluator.py`, ajouter l'import en tête :

```python
from aaosa.qa.adaptive import build_llm_spec
```

et à la fin du fichier :

```python
class AdaptiveSpecEvaluator:
    """Evaluator paresseux : génère la spec par tâche (B1) dans evaluate.

    Satisfait le Protocol QAEvaluator. La spec construite par build_llm_spec est
    interprétée par un SpecEvaluator (qui injecte le client dans llm_check et
    renseigne QAResult.spec_used). Aucun changement de signature côté runner.
    """

    def __init__(self, client: OpenAI):
        self.client = client

    def evaluate(self, task: Task, output: Output) -> QAResult:
        spec = build_llm_spec(task, self.client)
        return SpecEvaluator(spec, client=self.client).evaluate(task, output)
```

Ajouter les imports manquants en tête si absents : `from aaosa.schemas.task import Task`, `from aaosa.schemas.output import Output`, `from aaosa.qa.protocol import QAResult` (vérifier : `from openai import OpenAI` est déjà présent).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/qa/test_spec_evaluator.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `.venv\Scripts\python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/aaosa/qa/spec_evaluator.py tests/qa/test_spec_evaluator.py
git commit -m "feat(v3-b1): AdaptiveSpecEvaluator (spec LLM paresseuse par tache)"
```

---

## Task 6: Fix runner — tracer propagé à `execute` + `QAEvaluatedEvent.spec`

`run_task` doit passer le `tracer` à `execute` (pour émettre les `ToolCalledEvent`) et recopier `qa_result.spec_used` sur le `QAEvaluatedEvent`.

**Files:**
- Modify: `src/aaosa/runtime/runner.py:40` et bloc `QAEvaluatedEvent` (lignes ~57-67)
- Test: `tests/runtime/test_runner.py`

- [ ] **Step 1: Write the failing tests**

Ajouter dans `tests/runtime/test_runner.py` :

```python
def test_run_task_passes_tracer_to_execute():
    """run_task propage le tracer à execute (prérequis ToolCalledEvent)."""
    task = make_task()
    agent = make_agent("AgentA", 80)
    claim = make_claim(agent, task, "claim")
    output = make_output(agent, task)
    tracer = Tracer(session_id="s1")

    with patch.object(Agent, "claim", return_value=claim):
        with patch.object(Agent, "execute", return_value=output) as ex:
            run_task(task, [agent], MagicMock(), tracer=tracer)

    args, kwargs = ex.call_args
    passed = kwargs.get("tracer", args[2] if len(args) > 2 else None)
    assert passed is tracer


def test_run_task_qa_event_carries_spec():
    """L'event QA porte la spec issue de qa_result.spec_used."""
    from aaosa.qa.spec import CriterionSpec, EvaluatorSpec
    task = make_task()
    agent = make_agent("AgentA", 80)
    claim = make_claim(agent, task, "claim")
    output = make_output(agent, task)
    tracer = Tracer(session_id="s1")
    spec = EvaluatorSpec(criteria=[CriterionSpec(name="non_empty", gate=True)])

    class _SpecEvaluator:
        def evaluate(self, t, o):
            return QAResult(
                task_id=t.id, agent_id=o.agent_id, success=True, score=1.0,
                reason="ok", criteria_results={"non_empty": True}, spec_used=spec,
            )

    with patch.object(Agent, "claim", return_value=claim):
        with patch.object(Agent, "execute", return_value=output):
            run_task(task, [agent], MagicMock(), tracer=tracer, evaluator=_SpecEvaluator())

    qa_events = [e for e in tracer.events if isinstance(e, QAEvaluatedEvent)]
    assert len(qa_events) == 1
    assert qa_events[0].spec == spec
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_runner.py::test_run_task_passes_tracer_to_execute tests/runtime/test_runner.py::test_run_task_qa_event_carries_spec -v`
Expected: FAIL — le premier : `passed` vaut `None` (execute appelé avec 2 args) ; le second : `qa_events[0].spec` vaut `None`.

- [ ] **Step 3: Implement the fix**

Dans `src/aaosa/runtime/runner.py` :

a) Ligne 40, remplacer :

```python
    output = winner.execute(task, client)
```

par :

```python
    output = winner.execute(task, client, tracer)
```

b) Dans le bloc d'émission du `QAEvaluatedEvent` (après `qa_result = evaluator.evaluate(task, output)`), ajouter le champ `spec` :

```python
        tracer.emit(QAEvaluatedEvent(
            session_id=tracer.session_id,
            task_id=task.id,
            agent_id=winner.id,
            success=qa_result.success,
            score=qa_result.score,
            reason=qa_result.reason,
            criteria_results=qa_result.criteria_results,
            judge=qa_result.judge,
            spec=qa_result.spec_used,
        ))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_runner.py -v`
Expected: PASS (anciens + nouveaux ; les anciens tests qui patchent `execute` restent verts car le mock ignore l'argument supplémentaire).

- [ ] **Step 5: Run the full suite**

Run: `.venv\Scripts\python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/aaosa/runtime/runner.py tests/runtime/test_runner.py
git commit -m "fix(v3-a5): run_task propage le tracer a execute + QAEvaluatedEvent.spec"
```

---

## Task 7: Toolbox stubbée (`demo/tools.py`)

4 `ToolDef` déterministes + `attach_tools` qui les attache par nom d'agent.

**Files:**
- Create: `src/aaosa/demo/tools.py`
- Test: `tests/demo/test_tools.py`

- [ ] **Step 1: Write the failing test**

Créer `tests/demo/test_tools.py` :

```python
from aaosa.core.agent import Agent
from aaosa.core.tool import ToolDef
from aaosa.demo.tools import (
    TOOLBOX,
    attach_tools,
    explain_query_plan,
    grep_codebase,
    read_file,
    run_tests,
)


def _agent(name: str) -> Agent:
    return Agent(name=name, tags_with_elo={"python": 80}, system_prompt="x")


class TestToolFns:
    def test_all_fns_return_str(self):
        assert isinstance(read_file(path="api/middleware.py"), str)
        assert isinstance(grep_codebase(pattern="SELECT"), str)
        assert isinstance(run_tests(path="tests/"), str)
        assert isinstance(explain_query_plan(sql="SELECT 1"), str)

    def test_toolbox_is_tooldefs(self):
        assert all(isinstance(t, ToolDef) for t in TOOLBOX.values())
        assert {"read_file", "grep_codebase", "run_tests", "explain_query_plan"} == set(TOOLBOX)


class TestAttachTools:
    def test_attaches_by_name(self):
        agents = [_agent("Backend"), _agent("Frontend"), _agent("Fullstack"), _agent("DevOps")]
        attach_tools(agents)
        by_name = {a.name: a for a in agents}
        assert {t.name for t in by_name["Backend"].tools} == {
            "read_file", "grep_codebase", "run_tests", "explain_query_plan"}
        assert {t.name for t in by_name["Frontend"].tools} == {"read_file", "grep_codebase"}
        assert {t.name for t in by_name["Fullstack"].tools} == {"read_file", "run_tests"}
        assert {t.name for t in by_name["DevOps"].tools} == {"read_file"}

    def test_unknown_agent_gets_no_tools(self):
        agents = [_agent("Unknown")]
        attach_tools(agents)
        assert agents[0].tools == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/demo/test_tools.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aaosa.demo.tools'`.

- [ ] **Step 3: Implement the toolbox**

Créer `src/aaosa/demo/tools.py` :

```python
"""Toolbox stubbée déterministe pour la démo V3 (A5).

Les fn retournent des données figées mais réalistes (str). Attachées
programmatiquement (callables non sérialisables → impossibles dans agents.yaml).
"""

from aaosa.core.agent import Agent
from aaosa.core.tool import ToolDef

_FILES = {
    "api/middleware.py": (
        "async def auth_middleware(request, call_next):\n"
        "    token = request.headers.get('Authorization', '').removeprefix('Bearer ')\n"
        "    user = db.execute(f\"SELECT * FROM users WHERE token='{token}'\").fetchone()\n"
        "    # synchronous DB call on every request, no index on token (2M rows)\n"
    ),
    "reporting/queries.py": (
        "SELECT u.name, COUNT(o.id) FROM users u, orders o\n"
        "WHERE u.id = o.user_id GROUP BY u.id;  -- no index on o.user_id\n"
    ),
}


def read_file(path: str) -> str:
    return _FILES.get(path, f"[file not found: {path}]")


def grep_codebase(pattern: str) -> str:
    hits = [f"{p}: matches {pattern!r}" for p, c in _FILES.items() if pattern in c]
    return "\n".join(hits) if hits else f"no matches for {pattern!r}"


def run_tests(path: str) -> str:
    return (
        f"collected 3 items from {path}\n"
        "test_auth_middleware_uses_index PASSED\n"
        "test_reporting_query_fast PASSED\n"
        "test_no_regression PASSED\n"
        "3 passed in 0.42s\n"
    )


def explain_query_plan(sql: str) -> str:
    return (
        "Seq Scan on users  (cost=0.00..38221.00 rows=2000000)\n"
        "Seq Scan on orders (cost=0.00..51234.00 rows=15000000)\n"
        "-> no index used; full table scans on FK columns\n"
    )


def _tool(name: str, description: str, props: dict, fn) -> ToolDef:
    return ToolDef(
        name=name,
        description=description,
        parameters={"type": "object", "properties": props, "required": list(props)},
        fn=fn,
    )


TOOLBOX: dict[str, ToolDef] = {
    "read_file": _tool(
        "read_file", "Read the full contents of a source file by path.",
        {"path": {"type": "string"}}, read_file),
    "grep_codebase": _tool(
        "grep_codebase", "Search the codebase for a substring pattern.",
        {"pattern": {"type": "string"}}, grep_codebase),
    "run_tests": _tool(
        "run_tests", "Run the test suite under a given path and return the output.",
        {"path": {"type": "string"}}, run_tests),
    "explain_query_plan": _tool(
        "explain_query_plan", "Return the EXPLAIN plan for a SQL query.",
        {"sql": {"type": "string"}}, explain_query_plan),
}

_ASSIGNMENT: dict[str, list[str]] = {
    "Backend": ["read_file", "grep_codebase", "run_tests", "explain_query_plan"],
    "Frontend": ["read_file", "grep_codebase"],
    "Fullstack": ["read_file", "run_tests"],
    "DevOps": ["read_file"],
}


def attach_tools(agents: list[Agent]) -> None:
    """Mute agent.tools en place selon le nom (identifiant stable)."""
    for agent in agents:
        names = _ASSIGNMENT.get(agent.name, [])
        agent.tools = [TOOLBOX[n] for n in names]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/demo/test_tools.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/demo/tools.py tests/demo/test_tools.py
git commit -m "feat(v3-a5): toolbox stubbee + attach_tools pour la demo"
```

---

## Task 8: `demo/run_demo_v3.py` (démo runtime, incident divisé)

Un seul run divisé : incident → chaîne émergente → tool calls → spec LLM par sous-tâche → agrégation → persistance.

**Files:**
- Create: `src/aaosa/demo/run_demo_v3.py`
- Test: `tests/demo/test_run_demo_v3.py`

- [ ] **Step 1: Write the failing test**

Créer `tests/demo/test_run_demo_v3.py` :

```python
from aaosa.demo.run_demo_v3 import build_incident_task, run_demo_v3
from aaosa.schemas.task import Task


def test_build_incident_task_has_context_and_tags():
    task = build_incident_task()
    assert isinstance(task, Task)
    assert task.metadata.get("context")
    assert task.required_tags  # non vide

def test_run_demo_v3_is_callable():
    assert callable(run_demo_v3)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/demo/test_run_demo_v3.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aaosa.demo.run_demo_v3'`.

- [ ] **Step 3: Implement the demo script**

Créer `src/aaosa/demo/run_demo_v3.py` :

```python
"""Démo V3 runtime — incident de prod divisé, chaîne émergente, tool calls, B1.

Lancer : .venv\\Scripts\\python src\\aaosa\\demo\\run_demo_v3.py  (requiert OPENAI_API_KEY)
"""

from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from aaosa.demo.agents import DEMO_AGENTS
from aaosa.demo.tools import attach_tools
from aaosa.elo.persistence import save_snapshot
from aaosa.qa.spec_evaluator import AdaptiveSpecEvaluator
from aaosa.runtime.aggregator import TaskAggregator
from aaosa.runtime.divider import TaskDivider
from aaosa.runtime.llm_client import create_client
from aaosa.schemas.output import Output
from aaosa.schemas.task import Task
from aaosa.tracing.formatter import print_timeline
from aaosa.tracing.store import (
    SessionMeta,
    SessionTaskRecord,
    new_session_id,
    save_agent_registry,
    save_session,
)
from aaosa.tracing.tracer import Tracer

_INCIDENT_CONTEXT = """\
# Incident report — checkout returns intermittent 500s under load
# api/middleware.py (auth on every request)
async def auth_middleware(request, call_next):
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    user = db.execute(f"SELECT * FROM users WHERE token='{token}'").fetchone()
    ...
# reporting/queries.py — p99 > 8s
SELECT u.name, COUNT(o.id) FROM users u, orders o
WHERE u.id = o.user_id GROUP BY u.id;  -- no index on FK columns
# 2M users / 15M orders, no index on users.token nor orders.user_id"""


def build_incident_task() -> Task:
    return Task(
        description=(
            "The checkout endpoint returns intermittent 500s under load. We suspect "
            "the auth middleware and a slow reporting SQL query. Investigate the root "
            "cause, fix it, and add a regression test."
        ),
        required_tags={"backend": 70, "python": 70, "database": 60},
        metadata={"context": _INCIDENT_CONTEXT},
    )


def run_demo_v3() -> None:
    load_dotenv()
    client = create_client()
    runs_root = Path("runs")
    session_id = new_session_id()
    tracer = Tracer(session_id=session_id)
    started_at = datetime.now(timezone.utc)

    agents = list(DEMO_AGENTS)
    attach_tools(agents)
    evaluator = AdaptiveSpecEvaluator(client)

    divider = TaskDivider(system_prompt=(
        "You are a task decomposer. Break the task into the minimal set of ordered "
        "sub-tasks needed to fully resolve it. Express dependencies between sub-tasks. "
        "Prefer few, well-scoped sub-tasks, and include a final synthesis sub-task."
    ))
    aggregator = TaskAggregator(system_prompt=(
        "You are a synthesizer. Merge the sub-task results into one coherent, complete "
        "answer to the original incident."
    ))

    task = build_incident_task()
    print("=== AAOSA Demo V3 — divided incident run ===\n")
    print(f"Input: {task.description}\n")

    from aaosa.runtime.runner import run_divided_task
    result = run_divided_task(task, agents, client, divider, aggregator, tracer, evaluator)
    outcome = "divided" if isinstance(result, Output) else "unassigned"
    print(f"  -> {outcome}\n")

    print("=== Timeline ===")
    print_timeline(tracer.events)

    print("\n=== Persistence ===")
    save_agent_registry(agents, runs_root / "agents" / "registry.json")
    meta = SessionMeta(
        session_id=session_id,
        started_at=started_at,
        ended_at=datetime.now(timezone.utc),
        tasks=[SessionTaskRecord(
            id=task.id, description=task.description,
            winner_agent_id=None, outcome=outcome,
            required_tags=task.required_tags, context=task.metadata.get("context"),
        )],
        agent_ids=[a.id for a in agents],
    )
    session_dir = save_session(tracer, meta, runs_root, agents=agents)
    print(f"Session saved to {session_dir}")

    snapshot_dir = runs_root / "elo_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    path = save_snapshot(agents, snapshot_dir)
    print(f"ELO snapshot saved to {path}")


if __name__ == "__main__":
    run_demo_v3()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/demo/test_run_demo_v3.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/demo/run_demo_v3.py tests/demo/test_run_demo_v3.py
git commit -m "feat(v3): run_demo_v3 (incident divise + tools + spec LLM par sous-tache)"
```

---

## Task 9: `demo/run_health_check_v3.py` (boucle B2→B3→re-triage→health check)

Test set seedé avec cas `unattributed` (wrong_output canned), specs LLM par cas, orchestration de la boucle, rapport persisté.

**Files:**
- Create: `src/aaosa/demo/run_health_check_v3.py`
- Test: `tests/demo/test_run_health_check_v3.py`

- [ ] **Step 1: Write the failing test**

Créer `tests/demo/test_run_health_check_v3.py` :

```python
from aaosa.demo.run_health_check_v3 import build_seed_test_set, run_demo_health_check_v3
from aaosa.qa.test_set import TestSet


def test_build_seed_test_set_all_unattributed_with_wrong_output():
    ts = build_seed_test_set()
    assert isinstance(ts, TestSet)
    assert len(ts.cases) >= 1
    assert all(c.attribution == "unattributed" for c in ts.cases)
    assert all(c.origin == "runtime_failure" for c in ts.cases)
    assert all(c.wrong_output is not None for c in ts.cases)

def test_run_demo_health_check_v3_is_callable():
    assert callable(run_demo_health_check_v3)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/demo/test_run_health_check_v3.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aaosa.demo.run_health_check_v3'`.

- [ ] **Step 3: Implement the health check script**

Créer `src/aaosa/demo/run_health_check_v3.py` :

```python
"""Démo V3 health check — boucle d'auto-amélioration B2 (triage) → B3 (task spec) → re-triage.

Lancer : .venv\\Scripts\\python src\\aaosa\\demo\\run_health_check_v3.py  (requiert OPENAI_API_KEY)
"""

from pathlib import Path

from dotenv import load_dotenv

from aaosa.demo.agents import DEMO_AGENTS
from aaosa.demo.tasks import TASK_OPTIMIZE_SQL, TASK_REFACTOR_REST_API, TASK_SECURITY_AUDIT
from aaosa.qa.adaptive import build_llm_spec
from aaosa.qa.health_check import run_health_check, save_health_check
from aaosa.qa.task_spec_generator import fix_task_spec_cases
from aaosa.qa.test_set import TestCase, TestSet, active_cases
from aaosa.qa.triage import triage_unattributed
from aaosa.runtime.llm_client import create_client
from aaosa.schemas.output import LLMMetadata, Output
from aaosa.tracing.store import new_session_id
from aaosa.tracing.tracer import Tracer


def _wrong_output(task, content: str) -> Output:
    return Output(
        task_id=task.id, agent_id="seed-agent", content=content,
        llm_metadata=LLMMetadata(model_name="seed", tokens_in=1, tokens_out=1, latency_ms=1.0),
    )


def build_seed_test_set() -> TestSet:
    """Cas runtime_failure non attribués, avec wrong_output canned (matière au triage)."""
    from aaosa.qa.adaptive import build_adaptive_spec
    return TestSet(cases=[
        # output vraiment faible -> triage attendu "agent"
        TestCase(
            task=TASK_SECURITY_AUDIT,
            evaluator_spec=build_adaptive_spec(TASK_SECURITY_AUDIT),
            origin="runtime_failure", role="fix_target", attribution="unattributed",
            wrong_output=_wrong_output(TASK_SECURITY_AUDIT, "Looks fine to me."),
        ),
        # tâche ambiguë -> triage attendu "task_spec" -> corrigée par B3
        TestCase(
            task=TASK_REFACTOR_REST_API,
            evaluator_spec=build_adaptive_spec(TASK_REFACTOR_REST_API),
            origin="runtime_failure", role="fix_target", attribution="unattributed",
            wrong_output=_wrong_output(TASK_REFACTOR_REST_API, "I refactored some things."),
        ),
        TestCase(
            task=TASK_OPTIMIZE_SQL,
            evaluator_spec=build_adaptive_spec(TASK_OPTIMIZE_SQL),
            origin="runtime_failure", role="fix_target", attribution="unattributed",
            wrong_output=_wrong_output(TASK_OPTIMIZE_SQL, "Added an index."),
        ),
    ])


def _print_attributions(label: str, ts: TestSet) -> None:
    print(f"-- {label} --")
    for c in ts.cases:
        print(f"   [{c.attribution:<12}] {c.task.description[:55]}")
    print()


def run_demo_health_check_v3() -> None:
    load_dotenv()
    client = create_client()
    print("=== AAOSA Demo V3 — Health check + boucle B2/B3 ===\n")

    seed = build_seed_test_set()
    _print_attributions("Seed (toutes unattributed)", seed)

    triaged = triage_unattributed(seed, client)       # B2
    _print_attributions("Apres triage (B2)", triaged)

    fixed = fix_task_spec_cases(triaged, client)       # B3 (reset task_spec -> unattributed)
    _print_attributions("Apres correction task_spec (B3)", fixed)

    retriaged = triage_unattributed(fixed, client)     # re-triage
    _print_attributions("Apres re-triage (B2)", retriaged)

    active = active_cases(retriaged)
    print(f"Cas actifs : {len(active)}\n")

    tracer = Tracer(session_id=new_session_id())
    report = run_health_check(DEMO_AGENTS, retriaged, client, n_runs=3, tracer=tracer)

    print("=== Rapport ===")
    print(f"  fix_target pass rate       : {report.fix_target_pass_rate:.0%}")
    print(f"  regression_guard pass rate : {report.regression_guard_pass_rate:.0%}")
    for cr in report.case_results:
        flag = " [UNSTABLE]" if cr.unstable else ""
        print(f"    {cr.role:<16} pass={cr.pass_rate:.0%} ({cr.pass_count}/{cr.n_runs}){flag}")

    target = save_health_check(report, retriaged, tracer, Path("runs") / "health_checks", agents=DEMO_AGENTS)
    print(f"\nHealth check saved to {target}")


if __name__ == "__main__":
    run_demo_health_check_v3()
```

Note d'implémentation : `build_llm_spec` est importé mais le seed utilise `build_adaptive_spec` pour rester déterministe au build du test set ; pour exercer B1 dans le health check, remplacer `build_adaptive_spec(<task>)` par `build_llm_spec(<task>, client)` après avoir confirmé (Step 5) que `run_health_check` construit son `SpecEvaluator` avec le `client`. Si ce n'est pas le cas, garder `build_adaptive_spec` et signaler le gap (épique d'intégration health-check séparée).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv\Scripts\python -m pytest tests/demo/test_run_health_check_v3.py -v`
Expected: PASS.

- [ ] **Step 5: Verify health-check client wiring (manual read)**

Lire `src/aaosa/qa/health_check.py` : confirmer que le `SpecEvaluator` (ou `from_spec`) y est construit avec `client=client`. Si oui, basculer le seed sur `build_llm_spec(<task>, client)` pour exercer B1 (et relancer Step 4). Si non, conserver `build_adaptive_spec` et noter le gap dans le commit.

- [ ] **Step 6: Commit**

```bash
git add src/aaosa/demo/run_health_check_v3.py tests/demo/test_run_health_check_v3.py
git commit -m "feat(v3-b): run_health_check_v3 (boucle triage B2 -> task spec B3 -> re-triage)"
```

---

## Task 10: Validation end-to-end (LLM réel)

Vérification manuelle que les démos produisent les events attendus. Hors suite automatique (requiert `OPENAI_API_KEY`).

- [ ] **Step 1: Lancer la démo runtime**

Run: `.venv\Scripts\python src\aaosa\demo\run_demo_v3.py`
Expected (timeline) : une ligne `DIVIDED -> N sub-tasks`, des lignes de dispatch/exécution par sous-tâche, au moins une ligne tool call, une ligne `AGGREGATED <- N sub-tasks`, puis `Session saved to runs/sessions/<id>`.

- [ ] **Step 2: Inspecter la trace**

Vérifier dans `runs/sessions/<id>/trace.jsonl` la présence d'au moins : un event `task_divided` (avec `sub_tasks`), un `tool_called`, un `qa_evaluated` portant un champ `spec` non nul, un `task_aggregated`.

- [ ] **Step 3: Lancer la démo health check**

Run: `.venv\Scripts\python src\aaosa\demo\run_health_check_v3.py`
Expected : les blocs d'attributions montrent au moins un cas passant `unattributed → task_spec → unattributed → (agent|evaluator|...)` ; un rapport ; `Health check saved to runs/health_checks/<ts>`.

- [ ] **Step 4: Suite complète finale**

Run: `.venv\Scripts\python -m pytest -q`
Expected: PASS (669 + nouveaux tests, aucune régression).

---

## Notes de séquencement

- Tâches 1→2→3 : schémas (protocol, events). 4→5 : B1 (fix dette + evaluator paresseux). 6 : runner. 7 : toolbox. 8→9 : scripts démo. 10 : validation LLM réel.
- Chaque tâche laisse la suite verte (`pytest -q`) avant commit.
- Rappel instruction utilisateur : ne pas commit/push hors demande explicite. Les steps `git commit` ci-dessus sont la discipline TDD du plan ; pendant l'exécution, confirmer avec l'utilisateur avant de committer si ce n'est pas déjà autorisé.
