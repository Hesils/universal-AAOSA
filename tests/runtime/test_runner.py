"""Tests for run_task in aaosa.runtime.runner

Covers:
- Task assignment with qualified agents (Output returned)
- Task unassignment with unqualified agents (DispatchResult returned)
- Multi-claim conflict resolution (best fit wins)
- Tracer integration (ExecutedEvent emitted on assignment)
- No-tracer case (no error)
- Execute not called on unassignment
"""

from unittest.mock import MagicMock, patch
import pytest

from aaosa.runtime.runner import run_task
from aaosa.core.agent import Agent
from aaosa.schemas.claim import Claim
from aaosa.schemas.output import Output, LLMMetadata
from aaosa.schemas.task import Task
from aaosa.claiming.dispatch import DispatchResult
from aaosa.qa.protocol import QAResult, QAFailure
from aaosa.tracing.events import ExecutedEvent, QAEvaluatedEvent, EloUpdatedEvent, TagAcquiredEvent
from aaosa.tracing.tracer import Tracer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_agent(name: str = "AgentA", elo: int = 80) -> Agent:
    return Agent(
        name=name,
        tags_with_elo={"python": elo, "backend": elo},
        system_prompt=f"You are {name}.",
    )


def make_task() -> Task:
    return Task(
        description="Build a REST API endpoint",
        required_tags={"python": 60, "backend": 50},
    )


def make_claim(agent: Agent, task: Task, decision: str = "claim") -> Claim:
    return Claim(
        agent_id=agent.id,
        task_id=task.id,
        decision=decision,
        justification="ok",
    )


def make_output(agent: Agent, task: Task) -> Output:
    return Output(
        task_id=task.id,
        agent_id=agent.id,
        content="Done.",
        llm_metadata=LLMMetadata(
            model_name="gpt-4o-mini",
            tokens_in=10,
            tokens_out=5,
            latency_ms=100.0,
        ),
    )


# ---------------------------------------------------------------------------
# Test 1: Single qualified agent → Output
# ---------------------------------------------------------------------------

def test_run_task_assigned_returns_output():
    """One qualified agent (python:80, backend:80 > required 60, 50).
    Agent claims the task, executes, and returns Output."""
    task = make_task()
    agent = make_agent("AgentA", 80)
    claim = make_claim(agent, task, "claim")
    output = make_output(agent, task)

    with patch.object(Agent, "claim", return_value=claim):
        with patch.object(Agent, "execute", return_value=output):
            result = run_task(task, [agent], MagicMock())

    assert isinstance(result, Output)
    assert result.task_id == task.id
    assert result.agent_id == agent.id


# ---------------------------------------------------------------------------
# Test 2: Unqualified agent → DispatchResult with status='unassigned'
# ---------------------------------------------------------------------------

def test_run_task_unassigned_returns_dispatch_result():
    """Zero qualified agents (insufficient ELO: python:10, backend:10 < required 60, 50).
    Agent filtered out in phase1. No claim/execute calls. Returns DispatchResult."""
    task = make_task()
    unqualified_agent = make_agent("UnqualifiedAgent", 10)

    result = run_task(task, [unqualified_agent], MagicMock())

    assert isinstance(result, DispatchResult)
    assert result.status == "unassigned"


# ---------------------------------------------------------------------------
# Test 3: Multiple qualified agents → Best fit wins
# ---------------------------------------------------------------------------

def test_run_task_multi_claim_best_agent_wins():
    """Two qualified agents: a1 (python:90) and a2 (python:70).
    Both claim. a1 has higher fit_score, so a1's execute is called.
    Result is Output with a1.id."""
    task = make_task()
    a1 = make_agent("AgentA", 90)
    a2 = make_agent("AgentB", 70)

    claim_a1 = make_claim(a1, task, "claim")
    claim_a2 = make_claim(a2, task, "claim")
    output_a1 = make_output(a1, task)

    with patch.object(Agent, "claim", side_effect=[claim_a1, claim_a2]):
        with patch.object(Agent, "execute", return_value=output_a1) as execute_mock:
            result = run_task(task, [a1, a2], MagicMock())

    assert isinstance(result, Output)
    assert result.agent_id == a1.id
    assert execute_mock.call_count == 1


# ---------------------------------------------------------------------------
# Test 4: Tracer receives ExecutedEvent on assignment
# ---------------------------------------------------------------------------

def test_run_task_tracer_receives_executed_event():
    """One qualified agent, claims, executes. Tracer receives ExecutedEvent."""
    task = make_task()
    agent = make_agent("AgentA", 80)
    claim = make_claim(agent, task, "claim")
    output = make_output(agent, task)
    tracer = Tracer(session_id="s1")

    with patch.object(Agent, "claim", return_value=claim):
        with patch.object(Agent, "execute", return_value=output):
            result = run_task(task, [agent], MagicMock(), tracer=tracer)

    assert isinstance(result, Output)
    assert len(tracer.events) > 0
    last_event = tracer.events[-1]
    assert isinstance(last_event, ExecutedEvent)
    assert last_event.agent_id == agent.id


# ---------------------------------------------------------------------------
# Test 5: No tracer → No error
# ---------------------------------------------------------------------------

def test_run_task_no_tracer_no_error():
    """One qualified agent, tracer=None. No error occurs."""
    task = make_task()
    agent = make_agent("AgentA", 80)
    claim = make_claim(agent, task, "claim")
    output = make_output(agent, task)

    with patch.object(Agent, "claim", return_value=claim):
        with patch.object(Agent, "execute", return_value=output):
            result = run_task(task, [agent], MagicMock(), tracer=None)

    assert isinstance(result, Output)


# ---------------------------------------------------------------------------
# Test 6: Unassigned → Execute not called
# ---------------------------------------------------------------------------

def test_run_task_unassigned_no_execute_called():
    """Zero qualified agents. Execute should not be called."""
    task = make_task()
    unqualified_agent = make_agent("UnqualifiedAgent", 10)

    with patch.object(Agent, "execute") as execute_mock:
        result = run_task(task, [unqualified_agent], MagicMock())

    assert isinstance(result, DispatchResult)
    assert execute_mock.call_count == 0


# ---------------------------------------------------------------------------
# V2 helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# V2 Tests — Backward compat (evaluator=None)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# V2 Tests — QA pass
# ---------------------------------------------------------------------------

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
        task = make_task()
        agent = make_agent("A", 80)
        elo_before = dict(agent.tags_with_elo)
        claim = make_claim(agent, task, "claim")
        output = make_output(agent, task)
        evaluator = AlwaysPassEvaluator()
        with patch.object(Agent, "claim", return_value=claim):
            with patch.object(Agent, "execute", return_value=output):
                run_task(task, [agent], MagicMock(), evaluator=evaluator)
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


# ---------------------------------------------------------------------------
# V2 Tests — QA fail
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# V2 Tests — Tag acquisition
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# V2 Tests — Unassigned path unaffected
# ---------------------------------------------------------------------------

class TestRunTaskV2Unassigned:
    def test_unassigned_with_evaluator_returns_dispatch_result(self):
        """Unassigned task with evaluator -> DispatchResult (no QA, no ELO)."""
        task = make_task()
        agent = make_agent("Unqualified", 10)
        evaluator = AlwaysPassEvaluator()
        result = run_task(task, [agent], MagicMock(), evaluator=evaluator)
        assert isinstance(result, DispatchResult)
        assert result.status == "unassigned"
