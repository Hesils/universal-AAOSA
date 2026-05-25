"""Tests for the dispatch() function in claiming/dispatch.py."""

import pytest

from aaosa.claiming.dispatch import dispatch, DispatchResult
from aaosa.schemas.claim import Claim
from aaosa.schemas.task import Task
from aaosa.core.agent import Agent
from aaosa.tracing.tracer import Tracer
from aaosa.tracing.events import DispatchedEvent, UnassignedEvent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_task(required_tags: dict[str, int] | None = None) -> Task:
    return Task(
        description="test task",
        required_tags=required_tags or {"nlp": 800},
    )


def make_agent(agent_id: str, tags_with_elo: dict[str, int]) -> Agent:
    return Agent(
        id=agent_id,
        name=agent_id,
        tags_with_elo=tags_with_elo,
        system_prompt="You are a helpful agent.",
    )


def make_claim(agent_id: str, task_id: str, decision: str = "claim") -> Claim:
    return Claim(
        agent_id=agent_id,
        task_id=task_id,
        decision=decision,
        justification="ok",
    )


# ---------------------------------------------------------------------------
# Branch 0 — No claims
# ---------------------------------------------------------------------------

def test_no_claims_returns_unassigned():
    task = make_task()
    agents = [make_agent("a1", {"nlp": 800})]
    result = dispatch(
        claims=[],
        task=task,
        agents=agents,
        fit_scores={},
    )
    assert result.status == "unassigned"
    assert result.agent_id is None
    assert result.reason  # non-empty


def test_no_claims_with_no_claim_decisions_returns_unassigned():
    task = make_task()
    agents = [make_agent("a1", {"nlp": 800})]
    claim = make_claim("a1", task.id, decision="no_claim")
    result = dispatch(
        claims=[claim],
        task=task,
        agents=agents,
        fit_scores={"a1": 0.7},
    )
    assert result.status == "unassigned"
    assert result.agent_id is None
    assert result.reason


# ---------------------------------------------------------------------------
# Branch 1 — Single claim
# ---------------------------------------------------------------------------

def test_single_claim_returns_assigned():
    task = make_task()
    agents = [make_agent("a1", {"nlp": 900})]
    claim = make_claim("a1", task.id)
    result = dispatch(
        claims=[claim],
        task=task,
        agents=agents,
        fit_scores={"a1": 0.85},
    )
    assert result.status == "assigned"
    assert result.agent_id == "a1"
    assert result.reason == "sole claimer"


def test_single_claim_passes_through_all_claims_and_scores():
    task = make_task()
    agents = [make_agent("a1", {"nlp": 900}), make_agent("a2", {"nlp": 700})]
    c1 = make_claim("a1", task.id, decision="claim")
    c2 = make_claim("a2", task.id, decision="no_claim")
    result = dispatch(
        claims=[c1, c2],
        task=task,
        agents=agents,
        fit_scores={"a1": 0.9, "a2": 0.4},
    )
    assert result.agent_id == "a1"
    assert len(result.all_claims) == 2
    assert result.fit_scores == {"a1": 0.9, "a2": 0.4}


# ---------------------------------------------------------------------------
# Branch N — Multiple claims, different fit scores
# ---------------------------------------------------------------------------

def test_multiple_claims_highest_fit_score_wins():
    task = make_task({"nlp": 800})
    agents = [
        make_agent("a1", {"nlp": 850}),
        make_agent("a2", {"nlp": 900}),
        make_agent("a3", {"nlp": 820}),
    ]
    claims = [make_claim(a.id, task.id) for a in agents]
    fit_scores = {"a1": 0.6, "a2": 0.95, "a3": 0.75}
    result = dispatch(claims=claims, task=task, agents=agents, fit_scores=fit_scores)
    assert result.status == "assigned"
    assert result.agent_id == "a2"
    assert "fit score" in result.reason


def test_multiple_claims_score_in_reason():
    task = make_task({"nlp": 800})
    agents = [make_agent("a1", {"nlp": 900}), make_agent("a2", {"nlp": 850})]
    claims = [make_claim(a.id, task.id) for a in agents]
    fit_scores = {"a1": 0.9, "a2": 0.5}
    result = dispatch(claims=claims, task=task, agents=agents, fit_scores=fit_scores)
    assert "0.900" in result.reason


# ---------------------------------------------------------------------------
# Branch N — Exact fit score tie → tag ELO tie-break
# ---------------------------------------------------------------------------

def test_tie_broken_by_tag_elo():
    task = make_task({"nlp": 800, "vision": 600})
    # Both have same fit score, a2 has higher ELO on "nlp" (highest required ELO tag)
    agents = [
        make_agent("a1", {"nlp": 820, "vision": 700}),
        make_agent("a2", {"nlp": 900, "vision": 650}),
    ]
    claims = [make_claim(a.id, task.id) for a in agents]
    fit_scores = {"a1": 0.8, "a2": 0.8}
    result = dispatch(claims=claims, task=task, agents=agents, fit_scores=fit_scores)
    assert result.status == "assigned"
    assert result.agent_id == "a2"  # higher ELO on nlp (800 > 600 → nlp is first)
    assert result.reason == "tie-broken by tag ELO"


def test_tie_broken_by_secondary_tag_when_primary_tied():
    # a1 and a2 tied on "nlp" ELO, a2 wins on "vision" ELO (second tag by priority)
    task = make_task({"nlp": 800, "vision": 600})
    agents = [
        make_agent("a1", {"nlp": 900, "vision": 650}),
        make_agent("a2", {"nlp": 900, "vision": 850}),
    ]
    claims = [make_claim(a.id, task.id) for a in agents]
    fit_scores = {"a1": 0.8, "a2": 0.8}
    result = dispatch(claims=claims, task=task, agents=agents, fit_scores=fit_scores)
    assert result.agent_id == "a2"
    assert result.reason == "tie-broken by tag ELO"


def test_fully_degenerate_tie_returns_first_deterministically():
    # All claimers have identical ELO on all required tags → first in list wins
    task = make_task({"nlp": 800})
    agents = [
        make_agent("a1", {"nlp": 900}),
        make_agent("a2", {"nlp": 900}),
    ]
    claims = [make_claim(a.id, task.id) for a in agents]
    fit_scores = {"a1": 0.8, "a2": 0.8}
    result = dispatch(claims=claims, task=task, agents=agents, fit_scores=fit_scores)
    assert result.status == "assigned"
    # First in winner_claims wins deterministically
    assert result.agent_id == "a1"
    assert result.reason == "tie (degenerate config)"


# ---------------------------------------------------------------------------
# Tracer: UnassignedEvent on 0 claims
# ---------------------------------------------------------------------------

def test_tracer_receives_unassigned_event():
    task = make_task()
    tracer = Tracer(session_id="s1")
    result = dispatch(
        claims=[],
        task=task,
        agents=[],
        fit_scores={},
        tracer=tracer,
    )
    assert result.status == "unassigned"
    assert len(tracer.events) == 1
    event = tracer.events[0]
    assert isinstance(event, UnassignedEvent)
    assert event.session_id == "s1"
    assert event.task_id == task.id
    assert event.reason == "no agents claimed"


# ---------------------------------------------------------------------------
# Tracer: DispatchedEvent on assigned case
# ---------------------------------------------------------------------------

def test_tracer_receives_dispatched_event_single_claim():
    task = make_task()
    agents = [make_agent("a1", {"nlp": 900})]
    claim = make_claim("a1", task.id)
    tracer = Tracer(session_id="s2")
    result = dispatch(
        claims=[claim],
        task=task,
        agents=agents,
        fit_scores={"a1": 0.9},
        tracer=tracer,
    )
    assert result.status == "assigned"
    assert len(tracer.events) == 1
    event = tracer.events[0]
    assert isinstance(event, DispatchedEvent)
    assert event.session_id == "s2"
    assert event.task_id == task.id
    assert event.agent_id == "a1"
    assert event.reason == "sole claimer"


def test_tracer_receives_dispatched_event_multi_claim():
    task = make_task({"nlp": 800})
    agents = [make_agent("a1", {"nlp": 900}), make_agent("a2", {"nlp": 800})]
    claims = [make_claim(a.id, task.id) for a in agents]
    tracer = Tracer(session_id="s3")
    result = dispatch(
        claims=claims,
        task=task,
        agents=agents,
        fit_scores={"a1": 0.9, "a2": 0.5},
        tracer=tracer,
    )
    assert len(tracer.events) == 1
    event = tracer.events[0]
    assert isinstance(event, DispatchedEvent)
    assert event.agent_id == "a1"


# ---------------------------------------------------------------------------
# No tracer → no error
# ---------------------------------------------------------------------------

def test_no_tracer_no_error_unassigned():
    task = make_task()
    result = dispatch(claims=[], task=task, agents=[], fit_scores={}, tracer=None)
    assert result.status == "unassigned"


def test_no_tracer_no_error_assigned():
    task = make_task()
    agents = [make_agent("a1", {"nlp": 900})]
    claim = make_claim("a1", task.id)
    result = dispatch(
        claims=[claim],
        task=task,
        agents=agents,
        fit_scores={"a1": 0.9},
        tracer=None,
    )
    assert result.status == "assigned"
    assert result.agent_id == "a1"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_missing_agent_id_in_tie_break_raises():
    """Claim references agent_id absent from agents list during tie-break → ValueError."""
    task = make_task({"nlp": 800})
    # Both claims have same fit score (triggers tie-break), but "ghost" not in agents
    agents = [make_agent("a1", {"nlp": 900})]
    claims = [
        make_claim("a1", task.id),
        make_claim("ghost", task.id),
    ]
    fit_scores = {"a1": 0.8, "ghost": 0.8}
    with pytest.raises(ValueError, match="missing IDs"):
        dispatch(claims=claims, task=task, agents=agents, fit_scores=fit_scores)
