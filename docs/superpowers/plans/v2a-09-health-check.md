# V2a Subtask 09 — Health Check

_Statut: TODO_
_Depends on: subtask 02 (QA Protocol), subtask 08 (runner V2)_
_Blocking: subtask 10 (demo V2 — optionnel, le health check n'est pas dans la demo minimale)_

## Objectif

Implementer `run_health_check` qui execute un batch de taches de verification sur une liste d'agents et retourne un diagnostic de sante du systeme. Le health check **ne mute pas l'ELO** — c'est une operation read-only de verification.

Chaque entree du test suite est un couple `(Task, QAEvaluator)` car chaque tache peut necessiter un evaluateur different et predefini. Quand le runtime QA (subtask 08) remonte un echec, le caller ajoute le couple `(task, evaluator)` correspondant a la suite de health check pour re-verifier lors du prochain batch.

## Methode

TDD strict : ecrire les tests d'abord, puis implementer.

## Fichiers a creer

| Fichier | Action |
|---|---|
| `src/aaosa/qa/health_check.py` | CREER — run_health_check + HealthCheckReport + TestCase type alias |
| `tests/qa/test_health_check.py` | CREER — tests exhaustifs |

## Verification finale

```powershell
.venv\Scripts\python -m pytest tests/qa/test_health_check.py -v
.venv\Scripts\python -m pytest tests/ -v
```

---

## Context — Modules utilises

### `run_task` V2 (subtask 08, dans `runtime/runner.py`)

```python
def run_task(
    task: Task,
    agents: list[Agent],
    client: OpenAI,
    tracer: Tracer | None = None,
    evaluator: QAEvaluator | None = None,
) -> Output | DispatchResult | QAFailure:
```

Le health check appelle `run_task` en mode V1 (sans evaluator) pour obtenir l'output brut, puis evalue avec l'evaluateur specifique a chaque tache.

### `QAEvaluator` Protocol (subtask 02)

```python
@runtime_checkable
class QAEvaluator(Protocol):
    def evaluate(self, task: Task, output: Output) -> QAResult: ...
```

### `QAResult` (subtask 02)

```python
class QAResult(BaseModel):
    task_id: str
    agent_id: str
    success: bool
    score: float
    reason: str
    criteria_results: dict[str, bool]
```

### `QAFailure` (subtask 02)

```python
class QAFailure(BaseModel):
    task_id: str
    agent_id: str
    output: Output
    qa_result: QAResult
```

### `DispatchResult` (dans `claiming/dispatch.py`)

```python
class DispatchResult(BaseModel):
    status: Literal["assigned", "unassigned"]
    agent_id: str | None
    reason: str
    ...
```

### `Agent` (dans `core/agent.py`)

```python
class Agent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    tags_with_elo: dict[str, int]
    system_prompt: str
```

### `Tracer` (dans `tracing/tracer.py`)

```python
class Tracer:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.events: list[ClaimEvent] = []
    def emit(self, event: ClaimEvent) -> None:
        self.events.append(event)
```

---

## Design `run_health_check`

### Type alias pour la test suite

```python
TestCase = tuple[Task, QAEvaluator]
```

Chaque entree est un couple `(task, evaluator)`. L'evaluateur est predefini par le caller — il peut etre un `BasicRuleEvaluator`, un evaluateur LLM, ou n'importe quel objet satisfaisant le Protocol. Quand le runtime QA echoue sur un `(task, evaluator)`, le caller conserve ce couple et l'injecte dans la prochaine suite de health check.

### Signature

```python
def run_health_check(
    agents: list[Agent],
    test_suite: list[TestCase],
    client: OpenAI,
    tracer: Tracer | None = None,
) -> HealthCheckReport:
```

Pas de parametre `evaluator` global — chaque test case porte son propre evaluateur.

### Pipeline interne

Pour chaque `(task, evaluator)` dans test_suite :
1. `result = run_task(task, agents, client, tracer=tracer)` — V1 mode (pas d'evaluator)
2. Si `result` est un `DispatchResult` (unassigned) -> comptabiliser comme `skipped`
3. Si `result` est un `Output` -> `qa_result = evaluator.evaluate(task, result)`
4. Collecter le `QAResult` dans le rapport
5. Si echec -> creer un `QAFailure` et le collecter

**Pas de mutation ELO.** Le health check est diagnostic-only.

### HealthCheckReport

```python
class HealthCheckReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timestamp: datetime
    total_tasks: int
    passed: int
    failed: int
    skipped: int
    qa_results: list[QAResult]       # tous les resultats (pour audit)
    qa_failures: list[QAFailure]     # les echecs uniquement (pour debug + re-injection)
```

`total_tasks = passed + failed + skipped`.

---

## Etape 1 — Tests (RED)

Creer `tests/qa/test_health_check.py`.

Le health check appelle `run_task` qui utilise l'API LLM. Les tests doivent patcher `Agent.claim` et `Agent.execute` comme les tests du runner.

### Imports

```python
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from aaosa.qa.health_check import run_health_check, HealthCheckReport, TestCase
from aaosa.qa.protocol import QAResult, QAFailure, QAEvaluator
from aaosa.core.agent import Agent
from aaosa.schemas.task import Task
from aaosa.schemas.claim import Claim
from aaosa.schemas.output import Output, LLMMetadata
from aaosa.tracing.tracer import Tracer
```

### Helpers

```python
def make_agent(name: str = "A", elo: int = 80) -> Agent:
    return Agent(name=name, tags_with_elo={"python": elo}, system_prompt="test")

def make_task(required: dict[str, int] | None = None) -> Task:
    return Task(description="Test", required_tags=required or {"python": 50})

def make_claim(agent, task, decision="claim"):
    return Claim(agent_id=agent.id, task_id=task.id, decision=decision, justification="ok")

def make_output(agent, task, content="x" * 60 + " python"):
    return Output(
        task_id=task.id, agent_id=agent.id, content=content,
        llm_metadata=LLMMetadata(model_name="gpt-4o-mini", tokens_in=10, tokens_out=5, latency_ms=100.0),
    )

class AlwaysPassEvaluator:
    def evaluate(self, task, output):
        return QAResult(
            task_id=task.id, agent_id=output.agent_id,
            success=True, score=1.0, reason="ok", criteria_results={},
        )

class AlwaysFailEvaluator:
    def evaluate(self, task, output):
        return QAResult(
            task_id=task.id, agent_id=output.agent_id,
            success=False, score=0.0, reason="bad", criteria_results={},
        )
```

### Tests — HealthCheckReport schema

```python
class TestHealthCheckReport:
    def test_valid_report(self):
        r = HealthCheckReport(
            timestamp=datetime.now(timezone.utc),
            total_tasks=3, passed=2, failed=1, skipped=0,
            qa_results=[], qa_failures=[],
        )
        assert r.total_tasks == 3

    def test_extra_fields_forbidden(self):
        import pytest
        with pytest.raises(Exception):
            HealthCheckReport(
                timestamp=datetime.now(timezone.utc),
                total_tasks=0, passed=0, failed=0, skipped=0,
                qa_results=[], qa_failures=[], extra="bad",
            )
```

### Tests — Test suite avec evaluateurs par tache

```python
class TestRunHealthCheck:
    def test_all_pass(self):
        """Toutes les taches passent leur QA respectif."""
        agent = make_agent("A", 80)
        task = make_task()
        test_suite: list[TestCase] = [(task, AlwaysPassEvaluator())]
        claim = make_claim(agent, task)
        output = make_output(agent, task)
        with patch.object(Agent, "claim", return_value=claim):
            with patch.object(Agent, "execute", return_value=output):
                report = run_health_check(
                    agents=[agent], test_suite=test_suite,
                    client=MagicMock(),
                )
        assert report.passed == 1
        assert report.failed == 0
        assert report.total_tasks == 1
        assert len(report.qa_results) == 1
        assert report.qa_results[0].success is True

    def test_all_fail(self):
        """Toutes les taches echouent leur QA."""
        agent = make_agent("A", 80)
        task = make_task()
        test_suite: list[TestCase] = [(task, AlwaysFailEvaluator())]
        claim = make_claim(agent, task)
        output = make_output(agent, task)
        with patch.object(Agent, "claim", return_value=claim):
            with patch.object(Agent, "execute", return_value=output):
                report = run_health_check(
                    agents=[agent], test_suite=test_suite,
                    client=MagicMock(),
                )
        assert report.passed == 0
        assert report.failed == 1
        assert len(report.qa_failures) == 1
        assert report.qa_failures[0].qa_result.success is False

    def test_different_evaluator_per_task(self):
        """Chaque tache utilise son propre evaluateur."""
        agent = make_agent("A", 80)
        t1 = make_task()
        t2 = make_task()
        # t1 passe, t2 echoue — evaluateurs differents
        test_suite: list[TestCase] = [
            (t1, AlwaysPassEvaluator()),
            (t2, AlwaysFailEvaluator()),
        ]
        claim1 = make_claim(agent, t1)
        claim2 = make_claim(agent, t2)
        output1 = make_output(agent, t1)
        output2 = make_output(agent, t2)
        with patch.object(Agent, "claim", side_effect=[claim1, claim2]):
            with patch.object(Agent, "execute", side_effect=[output1, output2]):
                report = run_health_check(
                    agents=[agent], test_suite=test_suite,
                    client=MagicMock(),
                )
        assert report.passed == 1
        assert report.failed == 1
        assert report.total_tasks == 2

    def test_unassigned_task_skipped(self):
        """Tache unassigned -> skipped, pas de QA."""
        agent = make_agent("A", 10)  # trop faible pour required python:50
        task = make_task({"python": 50})
        test_suite: list[TestCase] = [(task, AlwaysPassEvaluator())]
        report = run_health_check(
            agents=[agent], test_suite=test_suite,
            client=MagicMock(),
        )
        assert report.skipped == 1
        assert report.passed == 0
        assert report.failed == 0
        assert len(report.qa_results) == 0

    def test_no_elo_mutation(self):
        """Le health check ne mute PAS l'ELO des agents."""
        agent = make_agent("A", 80)
        task = make_task()
        elo_before = dict(agent.tags_with_elo)
        test_suite: list[TestCase] = [(task, AlwaysPassEvaluator())]
        claim = make_claim(agent, task)
        output = make_output(agent, task)
        with patch.object(Agent, "claim", return_value=claim):
            with patch.object(Agent, "execute", return_value=output):
                run_health_check(
                    agents=[agent], test_suite=test_suite,
                    client=MagicMock(),
                )
        assert agent.tags_with_elo == elo_before

    def test_no_elo_mutation_on_failure(self):
        """Le health check ne mute PAS l'ELO meme sur echec QA."""
        agent = make_agent("A", 80)
        task = make_task()
        elo_before = dict(agent.tags_with_elo)
        test_suite: list[TestCase] = [(task, AlwaysFailEvaluator())]
        claim = make_claim(agent, task)
        output = make_output(agent, task)
        with patch.object(Agent, "claim", return_value=claim):
            with patch.object(Agent, "execute", return_value=output):
                run_health_check(
                    agents=[agent], test_suite=test_suite,
                    client=MagicMock(),
                )
        assert agent.tags_with_elo == elo_before

    def test_empty_test_suite(self):
        """Test suite vide -> rapport vide."""
        agent = make_agent("A", 80)
        report = run_health_check(
            agents=[agent], test_suite=[],
            client=MagicMock(),
        )
        assert report.total_tasks == 0
        assert report.passed == 0
        assert report.qa_results == []

    def test_tracer_optional(self):
        """tracer=None ne cause pas d'erreur."""
        agent = make_agent("A", 80)
        task = make_task()
        test_suite: list[TestCase] = [(task, AlwaysPassEvaluator())]
        claim = make_claim(agent, task)
        output = make_output(agent, task)
        with patch.object(Agent, "claim", return_value=claim):
            with patch.object(Agent, "execute", return_value=output):
                report = run_health_check(
                    agents=[agent], test_suite=test_suite,
                    client=MagicMock(), tracer=None,
                )
        assert isinstance(report, HealthCheckReport)

    def test_qa_failure_preserves_output(self):
        """QAFailure dans le rapport contient l'output rejete complet."""
        agent = make_agent("A", 80)
        task = make_task()
        test_suite: list[TestCase] = [(task, AlwaysFailEvaluator())]
        claim = make_claim(agent, task)
        output = make_output(agent, task, content="specific content for debugging")
        with patch.object(Agent, "claim", return_value=claim):
            with patch.object(Agent, "execute", return_value=output):
                report = run_health_check(
                    agents=[agent], test_suite=test_suite,
                    client=MagicMock(),
                )
        assert report.qa_failures[0].output.content == "specific content for debugging"

    def test_tracer_receives_qa_events(self):
        """Le tracer recoit les QAEvaluatedEvent du health check."""
        from aaosa.tracing.events import QAEvaluatedEvent
        agent = make_agent("A", 80)
        task = make_task()
        test_suite: list[TestCase] = [(task, AlwaysPassEvaluator())]
        claim = make_claim(agent, task)
        output = make_output(agent, task)
        tracer = Tracer(session_id="hc")
        with patch.object(Agent, "claim", return_value=claim):
            with patch.object(Agent, "execute", return_value=output):
                run_health_check(
                    agents=[agent], test_suite=test_suite,
                    client=MagicMock(), tracer=tracer,
                )
        qa_events = [e for e in tracer.events if isinstance(e, QAEvaluatedEvent)]
        assert len(qa_events) == 1
        assert qa_events[0].success is True
```

---

## Etape 2 — Implementation (GREEN)

Creer `src/aaosa/qa/health_check.py`.

```python
from datetime import datetime, timezone

from openai import OpenAI
from pydantic import BaseModel, ConfigDict

from aaosa.claiming.dispatch import DispatchResult
from aaosa.core.agent import Agent
from aaosa.qa.protocol import QAEvaluator, QAFailure, QAResult
from aaosa.runtime.runner import run_task
from aaosa.schemas.output import Output
from aaosa.schemas.task import Task
from aaosa.tracing.events import QAEvaluatedEvent
from aaosa.tracing.tracer import Tracer

TestCase = tuple[Task, QAEvaluator]


class HealthCheckReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timestamp: datetime
    total_tasks: int
    passed: int
    failed: int
    skipped: int
    qa_results: list[QAResult]
    qa_failures: list[QAFailure]


def run_health_check(
    agents: list[Agent],
    test_suite: list[TestCase],
    client: OpenAI,
    tracer: Tracer | None = None,
) -> HealthCheckReport:
    passed = 0
    failed = 0
    skipped = 0
    qa_results: list[QAResult] = []
    qa_failures: list[QAFailure] = []

    agent_map = {a.id: a for a in agents}

    for task, evaluator in test_suite:
        # V1 mode: run without evaluator to get raw output (no ELO mutation)
        result = run_task(task, agents, client, tracer=tracer)

        if isinstance(result, DispatchResult):
            skipped += 1
            continue

        # result is Output
        output = result
        qa_result = evaluator.evaluate(task, output)
        qa_results.append(qa_result)

        if tracer is not None:
            tracer.emit(QAEvaluatedEvent(
                session_id=tracer.session_id,
                task_id=task.id,
                agent_id=output.agent_id,
                success=qa_result.success,
                score=qa_result.score,
                reason=qa_result.reason,
            ))

        if qa_result.success:
            passed += 1
        else:
            failed += 1
            qa_failures.append(QAFailure(
                task_id=task.id,
                agent_id=output.agent_id,
                output=output,
                qa_result=qa_result,
            ))

    return HealthCheckReport(
        timestamp=datetime.now(timezone.utc),
        total_tasks=passed + failed + skipped,
        passed=passed,
        failed=failed,
        skipped=skipped,
        qa_results=qa_results,
        qa_failures=qa_failures,
    )
```

---

## Etape 3 — Tous les tests verts

```powershell
.venv\Scripts\python -m pytest tests/qa/test_health_check.py -v
.venv\Scripts\python -m pytest tests/ -v
```

## Invariants a respecter

- **Pas de mutation ELO** — le health check est diagnostic-only, read-only sur les agents
- Le health check appelle `run_task` en mode V1 (sans evaluator) pour eviter l'ELO update du pipeline V2
- Chaque `TestCase` est un couple `(Task, QAEvaluator)` — pas d'evaluateur global
- Les taches unassigned sont skipped (pas de QA possible, pas d'output)
- `total_tasks = passed + failed + skipped`
- `qa_results` contient TOUS les resultats (pass et fail) pour audit
- `qa_failures` contient seulement les echecs (pour debug + re-injection future)
- Le tracer est optionnel — emet `QAEvaluatedEvent` par tache evaluee (pas d'EloUpdatedEvent ni TagAcquiredEvent car pas de mutation ELO)
- Le stockage/accumulation du test set n'est PAS dans le scope V2a (scope V2b)
- Import absolu uniquement
