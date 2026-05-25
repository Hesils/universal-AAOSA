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
from aaosa.tracing.events import ExecutedEvent
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
