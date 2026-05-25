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
