# V2a Subtask 08 — Runtime Runner V2

_Statut: TODO_
_Depends on: subtask 02 (QA Protocol), subtask 03 (ELO updater), subtask 05 (tracer events V2)_
_Blocking: subtask 09 (health check), subtask 10 (demo V2)_

## Objectif

Modifier `run_task` pour accepter un `evaluator: QAEvaluator | None = None`. Quand evaluator est present, evaluer l'output, mettre a jour l'ELO, emettre les events tracer V2, et retourner `Output` ou `QAFailure`. Quand absent, comportement V1 identique.

**C'est la subtask d'integration centrale de V2a.**

## Methode

TDD strict : ecrire les tests d'abord, puis modifier le fichier existant.

## Fichiers a modifier

| Fichier | Action |
|---|---|
| `src/aaosa/runtime/runner.py` | MODIFIER — signature + pipeline V2 |
| `tests/runtime/test_runner.py` | MODIFIER — ajouter tests V2 |

## Verification finale

```powershell
.venv\Scripts\python -m pytest tests/runtime/test_runner.py -v
.venv\Scripts\python -m pytest tests/ -v   # TOUS les tests V1 + V2 doivent passer
```

---

## Context — Fichier existant `runtime/runner.py`

```python
from openai import OpenAI

from aaosa.claiming.dispatch import DispatchResult, dispatch
from aaosa.claiming.phase1 import filter_candidates
from aaosa.claiming.phase2 import run_phase2
from aaosa.core.agent import Agent
from aaosa.schemas.output import Output
from aaosa.schemas.task import Task
from aaosa.tracing.events import ExecutedEvent
from aaosa.tracing.tracer import Tracer


def run_task(
    task: Task,
    agents: list[Agent],
    client: OpenAI,
    tracer: Tracer | None = None,
) -> Output | DispatchResult:
    candidates = filter_candidates(task, agents, tracer)
    fit_scores = {agent.id: score for agent, score in candidates}
    claims = run_phase2(task, candidates, client, tracer)

    candidate_agents = [agent for agent, _ in candidates]
    result = dispatch(claims, task, candidate_agents, fit_scores, tracer)

    if result.status == "unassigned":
        return result

    agent_map = {agent.id: agent for agent in candidate_agents}
    winner = agent_map[result.agent_id]
    output = winner.execute(task, client)

    if tracer is not None:
        tracer.emit(ExecutedEvent(
            session_id=tracer.session_id,
            task_id=task.id,
            agent_id=winner.id,
            output_summary=output.content[:100],
        ))

    return output
```

## Context — Tests existants du runner

Le fichier `tests/runtime/test_runner.py` contient 6 tests V1 qui patchent `Agent.claim` et `Agent.execute`. Pattern :

```python
with patch.object(Agent, "claim", return_value=claim):
    with patch.object(Agent, "execute", return_value=output):
        result = run_task(task, [agent], MagicMock())
```

Ces 6 tests NE DOIVENT PAS etre modifies et DOIVENT continuer a passer.

## Context — Modules V2 utilises

### `QAEvaluator` Protocol (subtask 02)

```python
@runtime_checkable
class QAEvaluator(Protocol):
    def evaluate(self, task: Task, output: Output) -> QAResult: ...
```

### `QAFailure` (subtask 02)

```python
class QAFailure(BaseModel):
    task_id: str
    agent_id: str
    output: Output
    qa_result: QAResult
```

### `update_agent_elo` (subtask 03)

```python
def update_agent_elo(agent: Agent, task: Task, success: bool) -> EloUpdateResult:
    # Mute agent.tags_with_elo, retourne EloUpdateResult
```

### Tracer events V2 (subtask 05)

```python
class QAEvaluatedEvent(_BaseEvent):
    type: Literal["qa_evaluated"] = "qa_evaluated"
    agent_id: str
    success: bool
    score: float
    reason: str

class EloUpdatedEvent(_BaseEvent):
    type: Literal["elo_updated"] = "elo_updated"
    agent_id: str
    deltas: dict[str, int]

class TagAcquiredEvent(_BaseEvent):
    type: Literal["tag_acquired"] = "tag_acquired"
    agent_id: str
    tag: str
    initial_elo: int
```

---

## Etape 1 — Tests V2 (RED)

Ajouter dans `tests/runtime/test_runner.py`. NE PAS modifier les 6 tests V1 existants.

### Imports a ajouter

```python
from aaosa.qa.protocol import QAResult, QAEvaluator, QAFailure
from aaosa.elo.updater import EloUpdateResult
from aaosa.tracing.events import ExecutedEvent, QAEvaluatedEvent, EloUpdatedEvent, TagAcquiredEvent
```

### Helper evaluator

```python
class AlwaysPassEvaluator:
    def evaluate(self, task, output):
        return QAResult(
            task_id=task.id, agent_id=output.agent_id,
            success=True, score=1.0, reason="ok",
            criteria_results={"all": True},
        )

class AlwaysFailEvaluator:
    def evaluate(self, task, output):
        return QAResult(
            task_id=task.id, agent_id=output.agent_id,
            success=False, score=0.0, reason="bad",
            criteria_results={"all": False},
        )
```

### Tests — Backward compat (evaluator=None)

```python
class TestRunTaskV2BackwardCompat:
    def test_evaluator_none_returns_output(self):
        """evaluator=None -> V1 behavior exact, retourne Output."""
        task = make_task()
        agent = make_agent("A", 80)
        claim = make_claim(agent, task, "claim")
        output = make_output(agent, task)
        with patch.object(Agent, "claim", return_value=claim):
            with patch.object(Agent, "execute", return_value=output):
                result = run_task(task, [agent], MagicMock(), evaluator=None)
        assert isinstance(result, Output)

    def test_evaluator_none_no_elo_update(self):
        """evaluator=None -> pas d'ELO update, pas de QA events."""
        task = make_task()
        agent = make_agent("A", 80)
        original_elo = dict(agent.tags_with_elo)
        claim = make_claim(agent, task, "claim")
        output = make_output(agent, task)
        tracer = Tracer(session_id="s1")
        with patch.object(Agent, "claim", return_value=claim):
            with patch.object(Agent, "execute", return_value=output):
                run_task(task, [agent], MagicMock(), evaluator=None, tracer=tracer)
        assert agent.tags_with_elo == original_elo
        qa_events = [e for e in tracer.events if isinstance(e, QAEvaluatedEvent)]
        assert len(qa_events) == 0
```

### Tests — QA pass (evaluator present, success)

```python
class TestRunTaskV2QAPass:
    def test_qa_pass_returns_output(self):
        """QA pass -> retourne Output (pas QAFailure)."""
        task = make_task()
        agent = make_agent("A", 80)
        claim = make_claim(agent, task, "claim")
        output = make_output(agent, task)
        evaluator = AlwaysPassEvaluator()
        with patch.object(Agent, "claim", return_value=claim):
            with patch.object(Agent, "execute", return_value=output):
                result = run_task(task, [agent], MagicMock(), evaluator=evaluator)
        assert isinstance(result, Output)

    def test_qa_pass_updates_elo_up(self):
        """QA pass -> ELO augmente sur les required tags."""
        task = make_task()  # required: python:60, backend:50
        agent = make_agent("A", 80)  # python:80, backend:80
        elo_before = dict(agent.tags_with_elo)
        claim = make_claim(agent, task, "claim")
        output = make_output(agent, task)
        evaluator = AlwaysPassEvaluator()
        with patch.object(Agent, "claim", return_value=claim):
            with patch.object(Agent, "execute", return_value=output):
                run_task(task, [agent], MagicMock(), evaluator=evaluator)
        # Au moins un tag doit avoir augmente
        assert any(
            agent.tags_with_elo[t] > elo_before[t]
            for t in task.required_tags
        )

    def test_qa_pass_tracer_events(self):
        """QA pass -> tracer recoit QAEvaluatedEvent + EloUpdatedEvent."""
        task = make_task()
        agent = make_agent("A", 80)
        claim = make_claim(agent, task, "claim")
        output = make_output(agent, task)
        evaluator = AlwaysPassEvaluator()
        tracer = Tracer(session_id="s1")
        with patch.object(Agent, "claim", return_value=claim):
            with patch.object(Agent, "execute", return_value=output):
                run_task(task, [agent], MagicMock(), evaluator=evaluator, tracer=tracer)
        qa_events = [e for e in tracer.events if isinstance(e, QAEvaluatedEvent)]
        elo_events = [e for e in tracer.events if isinstance(e, EloUpdatedEvent)]
        assert len(qa_events) == 1
        assert qa_events[0].success is True
        assert len(elo_events) == 1
```

### Tests — QA fail (evaluator present, failure)

```python
class TestRunTaskV2QAFail:
    def test_qa_fail_returns_qa_failure(self):
        """QA fail -> retourne QAFailure."""
        task = make_task()
        agent = make_agent("A", 80)
        claim = make_claim(agent, task, "claim")
        output = make_output(agent, task)
        evaluator = AlwaysFailEvaluator()
        with patch.object(Agent, "claim", return_value=claim):
            with patch.object(Agent, "execute", return_value=output):
                result = run_task(task, [agent], MagicMock(), evaluator=evaluator)
        assert isinstance(result, QAFailure)
        assert result.output == output
        assert result.qa_result.success is False

    def test_qa_fail_updates_elo_down(self):
        """QA fail -> ELO diminue sur les required tags."""
        task = make_task()
        agent = make_agent("A", 80)
        elo_before = dict(agent.tags_with_elo)
        claim = make_claim(agent, task, "claim")
        output = make_output(agent, task)
        evaluator = AlwaysFailEvaluator()
        with patch.object(Agent, "claim", return_value=claim):
            with patch.object(Agent, "execute", return_value=output):
                run_task(task, [agent], MagicMock(), evaluator=evaluator)
        assert any(
            agent.tags_with_elo[t] < elo_before[t]
            for t in task.required_tags
        )

    def test_qa_fail_tracer_events(self):
        """QA fail -> tracer recoit QAEvaluatedEvent (success=False) + EloUpdatedEvent."""
        task = make_task()
        agent = make_agent("A", 80)
        claim = make_claim(agent, task, "claim")
        output = make_output(agent, task)
        evaluator = AlwaysFailEvaluator()
        tracer = Tracer(session_id="s1")
        with patch.object(Agent, "claim", return_value=claim):
            with patch.object(Agent, "execute", return_value=output):
                run_task(task, [agent], MagicMock(), evaluator=evaluator, tracer=tracer)
        qa_events = [e for e in tracer.events if isinstance(e, QAEvaluatedEvent)]
        assert len(qa_events) == 1
        assert qa_events[0].success is False
```

### Tests — Tag acquisition via tracer

```python
class TestRunTaskV2TagAcquisition:
    def test_qa_pass_with_acquirable_tags_emits_tag_acquired(self):
        """Succes + acquirable tag absent -> TagAcquiredEvent emis."""
        task = Task(
            description="Build API",
            required_tags={"python": 60},
            acquirable_tags={"docker": 20},
        )
        agent = Agent(
            name="A",
            tags_with_elo={"python": 80},
            system_prompt="test",
        )
        claim = make_claim(agent, task, "claim")
        output = make_output(agent, task)
        evaluator = AlwaysPassEvaluator()
        tracer = Tracer(session_id="s1")
        with patch.object(Agent, "claim", return_value=claim):
            with patch.object(Agent, "execute", return_value=output):
                run_task(task, [agent], MagicMock(), evaluator=evaluator, tracer=tracer)
        acq_events = [e for e in tracer.events if isinstance(e, TagAcquiredEvent)]
        assert len(acq_events) == 1
        assert acq_events[0].tag == "docker"
        assert acq_events[0].initial_elo == 20
```

### Tests — Unassigned path unaffected

```python
class TestRunTaskV2Unassigned:
    def test_unassigned_with_evaluator_returns_dispatch_result(self):
        """Unassigned task with evaluator -> DispatchResult (no QA, no ELO)."""
        task = make_task()
        agent = make_agent("Unqualified", 10)
        evaluator = AlwaysPassEvaluator()
        result = run_task(task, [agent], MagicMock(), evaluator=evaluator)
        assert isinstance(result, DispatchResult)
        assert result.status == "unassigned"
```

---

## Etape 2 — Implementation (GREEN)

Modifier `src/aaosa/runtime/runner.py`.

### Nouvelle signature

```python
from aaosa.qa.protocol import QAEvaluator, QAFailure
from aaosa.elo.updater import update_agent_elo
from aaosa.tracing.events import (
    ExecutedEvent,
    QAEvaluatedEvent,
    EloUpdatedEvent,
    TagAcquiredEvent,
)


def run_task(
    task: Task,
    agents: list[Agent],
    client: OpenAI,
    tracer: Tracer | None = None,
    evaluator: QAEvaluator | None = None,
) -> Output | DispatchResult | QAFailure:
```

**IMPORTANT** : `evaluator` est le DERNIER parametre (apres `tracer`) pour ne pas casser les appels V1 positionnels existants. Les 6 tests V1 appellent `run_task(task, [agent], MagicMock())` et `run_task(task, [agent], MagicMock(), tracer=tracer)` — ces formes doivent continuer a fonctionner.

### Pipeline V2 (apres la section output existante)

```python
    # ... existing code until output = winner.execute(task, client) ...

    if tracer is not None:
        tracer.emit(ExecutedEvent(
            session_id=tracer.session_id,
            task_id=task.id,
            agent_id=winner.id,
            output_summary=output.content[:100],
        ))

    # V2: QA evaluation + ELO update
    if evaluator is None:
        return output

    qa_result = evaluator.evaluate(task, output)

    if tracer is not None:
        tracer.emit(QAEvaluatedEvent(
            session_id=tracer.session_id,
            task_id=task.id,
            agent_id=winner.id,
            success=qa_result.success,
            score=qa_result.score,
            reason=qa_result.reason,
        ))

    elo_result = update_agent_elo(winner, task, success=qa_result.success)

    if tracer is not None:
        tracer.emit(EloUpdatedEvent(
            session_id=tracer.session_id,
            task_id=task.id,
            agent_id=winner.id,
            deltas=elo_result.deltas,
        ))
        for tag, elo in elo_result.acquired_tags.items():
            tracer.emit(TagAcquiredEvent(
                session_id=tracer.session_id,
                task_id=task.id,
                agent_id=winner.id,
                tag=tag,
                initial_elo=elo,
            ))

    if qa_result.success:
        return output
    else:
        return QAFailure(
            task_id=task.id,
            agent_id=winner.id,
            output=output,
            qa_result=qa_result,
        )
```

---

## Etape 3 — Tous les tests verts

```powershell
.venv\Scripts\python -m pytest tests/runtime/test_runner.py -v
.venv\Scripts\python -m pytest tests/ -v
```

## Invariants a respecter

- Les 6 tests V1 du runner NE DOIVENT PAS etre modifies
- `evaluator=None` = pipeline V1 EXACT (pas d'import QA/ELO si evaluator absent en runtime, mais les imports en haut du fichier sont OK)
- `evaluator` est le DERNIER parametre keyword pour ne pas casser les appels positionnels
- Ordre des events : ExecutedEvent -> QAEvaluatedEvent -> EloUpdatedEvent -> TagAcquiredEvent(s)
- Sur `result.status == "unassigned"`, on retourne immediatement le `DispatchResult` SANS evaluer (pas d'output a evaluer)
- Le tracer reste optionnel dans TOUS les cas (V1 et V2)
- `update_agent_elo` est appele MEME sur QA failure (pour penaliser l'ELO)
