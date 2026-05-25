"""
Tests for filter_candidates — aaosa.claiming.phase1
Group 1: Basic filtering (5 tests)
Group 2: Fit scores (3 tests)
Group 3: Tracer integration (5 tests)
Group 4: Edge cases (2 tests)
Total: 15 tests
"""

import pytest

from aaosa.claiming.phase1 import filter_candidates
from aaosa.claiming.scoring import fit_score
from aaosa.core.agent import Agent
from aaosa.schemas.task import Task
from aaosa.tracing.tracer import Tracer
from aaosa.tracing.events import Phase1FilteredEvent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_agent(tags: dict) -> Agent:
    return Agent(name="T", tags_with_elo=tags, system_prompt=".")


def make_task(required: dict, acquirable: dict | None = None) -> Task:
    return Task(description="T", required_tags=required, acquirable_tags=acquirable or {})


# ---------------------------------------------------------------------------
# Group 1 — Basic filtering (no tracer)
# ---------------------------------------------------------------------------

def test_all_pass():
    """All 3 agents have the required tag at sufficient ELO → 3 tuples returned."""
    task = make_task(required={"python": 50})
    agents = [
        make_agent({"python": 60}),
        make_agent({"python": 50}),
        make_agent({"python": 80}),
    ]
    result = filter_candidates(task, agents)
    assert len(result) == 3


def test_none_pass():
    """No agent has the required tag → empty list."""
    task = make_task(required={"python": 50})
    agents = [
        make_agent({"java": 70}),
        make_agent({"rust": 60}),
    ]
    result = filter_candidates(task, agents)
    assert result == []


def test_partial_pass():
    """2 of 4 agents satisfy required ELO → exactly 2 tuples with the right agents."""
    task = make_task(required={"backend": 60})
    agent_pass_1 = make_agent({"backend": 60})
    agent_pass_2 = make_agent({"backend": 90})
    agent_fail_1 = make_agent({"backend": 40})   # below threshold
    agent_fail_2 = make_agent({"frontend": 70})  # missing tag

    agents = [agent_pass_1, agent_fail_1, agent_pass_2, agent_fail_2]
    result = filter_candidates(task, agents)

    assert len(result) == 2
    returned_agents = [a for a, _ in result]
    assert agent_pass_1 in returned_agents
    assert agent_pass_2 in returned_agents


def test_returns_tuples():
    """Each item in result is a tuple of (Agent, float)."""
    task = make_task(required={"python": 50})
    agents = [make_agent({"python": 70}), make_agent({"python": 55})]
    result = filter_candidates(task, agents)
    for item in result:
        assert isinstance(item, tuple)
        assert len(item) == 2
        agent, score = item
        assert isinstance(agent, Agent)
        assert isinstance(score, float)


def test_empty_agents_list():
    """agents=[] → result is []."""
    task = make_task(required={"python": 50})
    result = filter_candidates(task, [])
    assert result == []


# ---------------------------------------------------------------------------
# Group 2 — Fit scores
# ---------------------------------------------------------------------------

def test_fit_score_correct():
    """The float in the tuple equals fit_score(agent, task) called directly."""
    task = make_task(required={"python": 50}, acquirable={"docker": 30})
    agent = make_agent({"python": 70, "docker": 20})
    result = filter_candidates(task, [agent])
    assert len(result) == 1
    _, score = result[0]
    expected = fit_score(agent, task)
    assert score == expected


def test_failing_agents_not_in_result():
    """Agents that fail passes_filter are absent from result (verified by agent id)."""
    task = make_task(required={"python": 80})
    agent_pass = make_agent({"python": 90})
    agent_fail = make_agent({"python": 50})  # below threshold

    result = filter_candidates(task, [agent_pass, agent_fail])
    returned_ids = {a.id for a, _ in result}
    assert agent_pass.id in returned_ids
    assert agent_fail.id not in returned_ids


def test_fit_score_is_float():
    """isinstance(score, float) is True for all scores in result."""
    task = make_task(required={"python": 40})
    agents = [make_agent({"python": 50}), make_agent({"python": 60})]
    result = filter_candidates(task, agents)
    for _, score in result:
        assert isinstance(score, float)


# ---------------------------------------------------------------------------
# Group 3 — Tracer integration
# ---------------------------------------------------------------------------

def test_emits_event_for_every_agent():
    """With 4 agents (2 pass, 2 fail): len(tracer.events) == 4."""
    task = make_task(required={"backend": 60})
    agents = [
        make_agent({"backend": 70}),   # pass
        make_agent({"backend": 80}),   # pass
        make_agent({"backend": 40}),   # fail (below threshold)
        make_agent({"frontend": 70}),  # fail (missing tag)
    ]
    tracer = Tracer(session_id="test-session")
    filter_candidates(task, agents, tracer=tracer)
    assert len(tracer.events) == 4


def test_event_passed_true_for_passing_agent():
    """Event with passed=True is emitted for an agent that qualifies."""
    task = make_task(required={"python": 50})
    agent = make_agent({"python": 70})
    tracer = Tracer(session_id="test-session")
    filter_candidates(task, [agent], tracer=tracer)
    assert len(tracer.events) == 1
    event = tracer.events[0]
    assert isinstance(event, Phase1FilteredEvent)
    assert event.passed is True
    assert event.agent_id == agent.id


def test_event_passed_false_for_failing_agent():
    """Event with passed=False is emitted for a filtered-out agent."""
    task = make_task(required={"python": 80})
    agent = make_agent({"python": 40})  # below threshold
    tracer = Tracer(session_id="test-session")
    filter_candidates(task, [agent], tracer=tracer)
    assert len(tracer.events) == 1
    event = tracer.events[0]
    assert isinstance(event, Phase1FilteredEvent)
    assert event.passed is False
    assert event.agent_id == agent.id


def test_event_fit_score_matches_tuple():
    """event.fit_score == score_in_tuple for a passing agent."""
    task = make_task(required={"python": 50}, acquirable={"docker": 20})
    agent = make_agent({"python": 70, "docker": 15})
    tracer = Tracer(session_id="test-session")
    result = filter_candidates(task, [agent], tracer=tracer)
    assert len(result) == 1
    _, tuple_score = result[0]
    event = tracer.events[0]
    assert event.fit_score == tuple_score


def test_no_tracer_no_exception():
    """tracer=None raises no exception and returns correct result."""
    task = make_task(required={"python": 50})
    agent = make_agent({"python": 60})
    result = filter_candidates(task, [agent], tracer=None)
    assert len(result) == 1


# ---------------------------------------------------------------------------
# Group 4 — Edge cases
# ---------------------------------------------------------------------------

def test_acquirable_tag_does_not_block():
    """Agent missing an acquirable tag still passes (passes_filter ignores acquirable_tags)."""
    task = make_task(required={"backend": 50}, acquirable={"docker": 20})
    agent = make_agent({"backend": 60})  # has required but not acquirable
    result = filter_candidates(task, [agent])
    assert len(result) == 1  # passes because required is satisfied


def test_exact_elo_threshold_passes():
    """Agent at exactly required ELO passes the filter."""
    task = make_task(required={"python": 40})
    agent = make_agent({"python": 40})  # exactly at threshold
    result = filter_candidates(task, [agent])
    assert len(result) == 1
