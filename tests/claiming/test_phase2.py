import pytest
from aaosa.claiming.prompts import prompt_template
from aaosa.core.agent import Agent
from aaosa.schemas.task import Task


@pytest.fixture
def agent():
    return Agent(
        name="BackendAgent",
        tags_with_elo={"python": 80, "backend": 70},
        system_prompt="You are a backend specialist.",
    )


@pytest.fixture
def task():
    return Task(
        description="Refactor REST API to OpenAPI 3.1",
        required_tags={"python": 60, "backend": 50},
    )


def test_prompt_template_returns_string(agent, task):
    """Test that prompt_template returns a string."""
    result = prompt_template(agent, task)
    assert isinstance(result, str)


def test_prompt_template_contains_task_description(agent, task):
    """Test that the prompt contains the task description."""
    result = prompt_template(agent, task)
    assert task.description in result


def test_prompt_template_contains_required_tag_keys(agent, task):
    """Test that the prompt contains all required tag keys."""
    result = prompt_template(agent, task)
    for tag_key in task.required_tags.keys():
        assert tag_key in result


def test_prompt_template_contains_required_tag_thresholds(agent, task):
    """Test that the prompt contains all required tag threshold values as strings."""
    result = prompt_template(agent, task)
    for threshold in task.required_tags.values():
        assert str(threshold) in result


def test_prompt_template_contains_system_prompt(agent, task):
    """Test that the prompt contains the agent's system prompt."""
    result = prompt_template(agent, task)
    assert agent.system_prompt in result


def test_prompt_template_not_empty(agent, task):
    """Test that the prompt is not empty."""
    result = prompt_template(agent, task)
    assert len(result) > 0


def test_prompt_template_mentions_claim(agent, task):
    """Test that the prompt mentions 'claim' (case-insensitive)."""
    result = prompt_template(agent, task)
    assert "claim" in result.lower()


def test_prompt_template_mentions_justification(agent, task):
    """Test that the prompt asks for justification/reason/explanation."""
    result = prompt_template(agent, task)
    lower_result = result.lower()
    assert any(keyword in lower_result for keyword in ["justif", "reason", "explain"])


def test_prompt_template_no_fit_score_injected():
    """Test that the prompt does not inject ELO-derived fit scores.

    Agents with different ELO scores but same name and system prompt
    should produce identical prompts for the same task.
    """
    agent_high = Agent(
        name="A",
        tags_with_elo={"python": 95, "backend": 90},
        system_prompt="Same prompt.",
    )
    agent_low = Agent(
        name="A",
        tags_with_elo={"python": 30, "backend": 28},
        system_prompt="Same prompt.",
    )
    task = Task(
        description="Refactor API",
        required_tags={"python": 28, "backend": 28},
    )

    assert prompt_template(agent_high, task) == prompt_template(agent_low, task)


from unittest.mock import patch, MagicMock
from aaosa.claiming.phase2 import run_phase2_async
from aaosa.schemas.claim import Claim
from aaosa.tracing.events import Phase2ClaimedEvent
from aaosa.tracing.tracer import Tracer


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
def async_task():
    return Task(
        description="Build a REST API endpoint",
        required_tags={"python": 60, "backend": 50},
    )


@pytest.fixture
def async_provider():
    from aaosa.runtime.providers import LLMProvider
    return MagicMock(spec=LLMProvider)


@pytest.mark.asyncio
async def test_async_all_succeed(async_task, async_provider):
    """Test that all agents succeed and claims are returned in order."""
    agent_a = make_agent("AgentA")
    agent_b = make_agent("AgentB")
    claim_a = make_claim(agent_a, async_task)
    claim_b = make_claim(agent_b, async_task)

    candidates = [(agent_a, 0.9), (agent_b, 0.8)]

    with patch.object(Agent, "claim", side_effect=[claim_a, claim_b]):
        result = await run_phase2_async(async_task, candidates, async_provider)

    assert len(result) == 2
    assert result[0].agent_id == agent_a.id
    assert result[1].agent_id == agent_b.id


@pytest.mark.asyncio
async def test_async_one_fails_twice_skipped(async_task, async_provider):
    """Test that an agent failing twice is skipped silently."""
    agent = make_agent("AgentA")
    candidates = [(agent, 0.9)]

    with patch.object(Agent, "claim", side_effect=[Exception("fail1"), Exception("fail2")]):
        result = await run_phase2_async(async_task, candidates, async_provider)

    assert len(result) == 0


@pytest.mark.asyncio
async def test_async_empty_candidates(async_task, async_provider):
    """Test that empty candidates list returns empty result."""
    result = await run_phase2_async(async_task, [], async_provider)
    assert result == []


@pytest.mark.asyncio
async def test_async_tracer_receives_events(async_task, async_provider):
    """Test that tracer receives Phase2ClaimedEvent for each successful claim."""
    agent_a = make_agent("AgentA")
    agent_b = make_agent("AgentB")
    claim_a = make_claim(agent_a, async_task)
    claim_b = make_claim(agent_b, async_task)

    candidates = [(agent_a, 0.9), (agent_b, 0.8)]
    tracer = Tracer(session_id="s1")

    with patch.object(Agent, "claim", side_effect=[claim_a, claim_b]):
        result = await run_phase2_async(async_task, candidates, async_provider, tracer=tracer)

    assert len(tracer.events) == 2
    assert all(isinstance(event, Phase2ClaimedEvent) for event in tracer.events)
    assert tracer.events[0].agent_id == agent_a.id
    assert tracer.events[1].agent_id == agent_b.id
    assert tracer.events[0].decision == "claim"
    assert tracer.events[1].decision == "claim"


@pytest.mark.asyncio
async def test_async_one_fails_then_retries_success(async_task, async_provider):
    """Test that retry succeeds after initial failure."""
    agent = make_agent("AgentA")
    claim = make_claim(agent, async_task)

    candidates = [(agent, 0.9)]

    with patch.object(Agent, "claim", side_effect=[Exception("timeout"), claim]):
        result = await run_phase2_async(async_task, candidates, async_provider)

    assert len(result) == 1
    assert result[0].agent_id == agent.id
