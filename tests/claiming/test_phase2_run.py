"""Tests for run_phase2 (phase2.py) — with retry logic and tracer integration."""
from unittest.mock import MagicMock, patch

import pytest

from aaosa.claiming.phase2 import run_phase2
from aaosa.core.agent import Agent
from aaosa.schemas.claim import Claim
from aaosa.schemas.task import Task
from aaosa.tracing.events import Phase2ClaimedEvent
from aaosa.tracing.tracer import Tracer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def task():
    return Task(
        description="Build a REST API endpoint",
        required_tags={"python": 60, "backend": 50},
    )


def make_agent(name: str = "AgentA") -> Agent:
    return Agent(
        name=name,
        tags_with_elo={"python": 80, "backend": 70},
        system_prompt=f"You are {name}.",
    )


def make_claim(agent: Agent, task: Task, decision: str = "claim") -> Claim:
    return Claim(
        agent_id=agent.id,
        task_id=task.id,
        decision=decision,
        justification=f"{decision} justification",
    )


@pytest.fixture
def client():
    return MagicMock()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_all_succeed_first_attempt(task, client):
    """2 agents, both succeed on first call → 2 claims returned."""
    agent_a = make_agent("AgentA")
    agent_b = make_agent("AgentB")
    claim_a = make_claim(agent_a, task, "claim")
    claim_b = make_claim(agent_b, task, "claim")

    with patch.object(Agent, "claim", side_effect=[claim_a, claim_b]):
        result = run_phase2(task, [(agent_a, 0.9), (agent_b, 0.8)], client)

    assert len(result) == 2
    assert result[0] is claim_a
    assert result[1] is claim_b


def test_one_fails_then_retries_success(task, client):
    """1 agent raises on attempt 0, succeeds on attempt 1 (retry) → 1 claim returned."""
    agent = make_agent("AgentA")
    claim = make_claim(agent, task, "claim")

    # side_effect list: [exception on first call, success on retry]
    with patch.object(Agent, "claim", side_effect=[Exception("timeout"), claim]):
        result = run_phase2(task, [(agent, 0.9)], client)

    assert len(result) == 1
    assert result[0] is claim


def test_one_fails_twice_skipped(task, client):
    """1 agent raises on both attempts → 0 claims returned, no exception raised."""
    agent = make_agent("AgentA")

    with patch.object(Agent, "claim", side_effect=[Exception("fail1"), Exception("fail2")]):
        result = run_phase2(task, [(agent, 0.9)], client)

    assert len(result) == 0


def test_mixed_success_fail_retry_skip(task, client):
    """
    3 agents:
    - Agent A succeeds on first attempt
    - Agent B fails, retries, succeeds
    - Agent C fails twice (skipped)
    → 2 claims returned in order (A, B), no exception
    """
    agent_a = make_agent("AgentA")
    agent_b = make_agent("AgentB")
    agent_c = make_agent("AgentC")

    claim_a = make_claim(agent_a, task, "claim")
    claim_b = make_claim(agent_b, task, "claim")

    # Order: A succeeds, B fails then succeeds, C fails twice
    side_effects = [claim_a, Exception("timeout"), claim_b, Exception("fail1"), Exception("fail2")]

    with patch.object(Agent, "claim", side_effect=side_effects):
        result = run_phase2(
            task,
            [(agent_a, 0.9), (agent_b, 0.7), (agent_c, 0.5)],
            client
        )

    assert len(result) == 2
    assert result[0] is claim_a
    assert result[1] is claim_b


def test_tracer_emits_for_successful_claims(task, client):
    """2 agents succeed → tracer has 2 Phase2ClaimedEvents with correct agent_ids."""
    agent_a = make_agent("AgentA")
    agent_b = make_agent("AgentB")
    claim_a = make_claim(agent_a, task, "claim")
    claim_b = make_claim(agent_b, task, "no_claim")

    tracer = Tracer(session_id="session-test-1")

    with patch.object(Agent, "claim", side_effect=[claim_a, claim_b]):
        result = run_phase2(task, [(agent_a, 0.9), (agent_b, 0.5)], client, tracer=tracer)

    assert len(result) == 2
    assert len(tracer.events) == 2

    event_a = tracer.events[0]
    assert isinstance(event_a, Phase2ClaimedEvent)
    assert event_a.agent_id == agent_a.id
    assert event_a.task_id == task.id
    assert event_a.decision == "claim"

    event_b = tracer.events[1]
    assert isinstance(event_b, Phase2ClaimedEvent)
    assert event_b.agent_id == agent_b.id
    assert event_b.task_id == task.id
    assert event_b.decision == "no_claim"


def test_empty_candidates_returns_empty(task, client):
    """Empty candidates list → empty result list."""
    result = run_phase2(task, [], client)
    assert result == []


def test_tracer_none_no_error(task, client):
    """1 agent succeeds, tracer=None → no exception, 1 claim returned."""
    agent = make_agent("AgentA")
    claim = make_claim(agent, task, "claim")

    with patch.object(Agent, "claim", return_value=claim):
        result = run_phase2(task, [(agent, 0.9)], client, tracer=None)

    assert len(result) == 1
    assert result[0] is claim
