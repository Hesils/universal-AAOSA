"""Tests for collect_claims (phase2.py)."""
from unittest.mock import MagicMock, patch

import pytest

from aaosa.claiming.phase2 import collect_claims
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

def test_no_candidates_returns_empty_list(task, client):
    result = collect_claims(task, [], client)
    assert result == []


def test_one_candidate_returns_one_claim(task, client):
    agent = make_agent("AgentA")
    claim = make_claim(agent, task, "claim")

    with patch.object(Agent, "claim", return_value=claim):
        result = collect_claims(task, [(agent, 0.9)], client)

    assert len(result) == 1
    assert result[0] is claim


def test_two_candidates_returns_two_claims_in_order(task, client):
    agent_a = make_agent("AgentA")
    agent_b = make_agent("AgentB")
    claim_a = make_claim(agent_a, task, "claim")
    claim_b = make_claim(agent_b, task, "no_claim")

    side_effects = [claim_a, claim_b]

    with patch.object(Agent, "claim", side_effect=side_effects):
        result = collect_claims(task, [(agent_a, 0.9), (agent_b, 0.5)], client)

    assert len(result) == 2
    assert result[0] is claim_a
    assert result[1] is claim_b


def test_no_claim_decision_is_included(task, client):
    agent = make_agent("AgentA")
    claim = make_claim(agent, task, "no_claim")

    with patch.object(Agent, "claim", return_value=claim):
        result = collect_claims(task, [(agent, 0.4)], client)

    assert len(result) == 1
    assert result[0].decision == "no_claim"


def test_tracer_receives_one_event_per_candidate(task, client):
    agent_a = make_agent("AgentA")
    agent_b = make_agent("AgentB")
    claim_a = make_claim(agent_a, task, "claim")
    claim_b = make_claim(agent_b, task, "no_claim")

    tracer = Tracer(session_id="session-test-1")

    with patch.object(Agent, "claim", side_effect=[claim_a, claim_b]):
        collect_claims(task, [(agent_a, 0.9), (agent_b, 0.5)], client, tracer=tracer)

    assert len(tracer.events) == 2

    event_a = tracer.events[0]
    assert isinstance(event_a, Phase2ClaimedEvent)
    assert event_a.agent_id == agent_a.id
    assert event_a.task_id == task.id
    assert event_a.decision == "claim"
    assert event_a.session_id == "session-test-1"

    event_b = tracer.events[1]
    assert isinstance(event_b, Phase2ClaimedEvent)
    assert event_b.agent_id == agent_b.id
    assert event_b.decision == "no_claim"


def test_no_tracer_does_not_raise(task, client):
    agent = make_agent("AgentA")
    claim = make_claim(agent, task, "claim")

    with patch.object(Agent, "claim", return_value=claim):
        result = collect_claims(task, [(agent, 0.8)], client, tracer=None)

    assert len(result) == 1


def test_fit_score_ignored(task, client):
    """The float (fit_score) in the tuple is ignored — only agent matters."""
    agent = make_agent("AgentA")
    claim = make_claim(agent, task, "claim")

    with patch.object(Agent, "claim", return_value=claim) as mock_claim:
        result = collect_claims(task, [(agent, 9999.0)], client)

    mock_claim.assert_called_once_with(task, client)
    assert len(result) == 1


def test_exception_propagates(task, client):
    """Exceptions from agent.claim() propagate — no swallowing."""
    agent = make_agent("AgentA")

    with patch.object(Agent, "claim", side_effect=RuntimeError("LLM failed")):
        with pytest.raises(RuntimeError, match="LLM failed"):
            collect_claims(task, [(agent, 0.5)], client)
