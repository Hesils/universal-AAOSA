"""Tests for the Agent class in the AAOSA core module."""

import pytest
from pydantic import ValidationError

from aaosa.core.agent import Agent
from aaosa.schemas.task import Task


class TestAgentCreation:
    """Tests for Agent instantiation and field validation."""

    def test_agent_valid_creation(self):
        """Test Agent creation with all required fields."""
        agent = Agent(
            id="agent-123",
            name="TestAgent",
            tags_with_elo={"python": 75, "ml": 60},
            system_prompt="You are a test agent."
        )
        assert agent.id == "agent-123"
        assert agent.name == "TestAgent"
        assert agent.tags_with_elo == {"python": 75, "ml": 60}
        assert agent.system_prompt == "You are a test agent."

    def test_agent_id_auto_generated(self):
        """Test that agent id is auto-generated when omitted."""
        agent = Agent(
            name="TestAgent",
            tags_with_elo={"python": 75},
            system_prompt="You are a test agent."
        )
        assert isinstance(agent.id, str)
        assert len(agent.id) > 0

    def test_agent_two_instances_have_different_ids(self):
        """Test that two agents created without explicit ids have different ids."""
        agent1 = Agent(
            name="Agent1",
            tags_with_elo={"python": 75},
            system_prompt="Agent 1 prompt"
        )
        agent2 = Agent(
            name="Agent2",
            tags_with_elo={"python": 75},
            system_prompt="Agent 2 prompt"
        )
        assert agent1.id != agent2.id

    def test_agent_name_required(self):
        """Test that name field is required."""
        with pytest.raises(ValidationError):
            Agent(
                tags_with_elo={"python": 75},
                system_prompt="You are a test agent."
            )

    def test_agent_system_prompt_required(self):
        """Test that system_prompt field is required."""
        with pytest.raises(ValidationError):
            Agent(
                name="TestAgent",
                tags_with_elo={"python": 75}
            )

    def test_agent_tags_with_elo_required(self):
        """Test that tags_with_elo field is required."""
        with pytest.raises(ValidationError):
            Agent(
                name="TestAgent",
                system_prompt="You are a test agent."
            )

    def test_agent_tags_with_elo_empty_raises(self):
        """Test that empty tags_with_elo raises ValidationError."""
        with pytest.raises(ValidationError):
            Agent(
                name="TestAgent",
                tags_with_elo={},
                system_prompt="You are a test agent."
            )

    def test_agent_extra_fields_forbidden(self):
        """Test that extra fields raise ValidationError."""
        with pytest.raises(ValidationError):
            Agent(
                name="TestAgent",
                tags_with_elo={"python": 75},
                system_prompt="You are a test agent.",
                foo="bar"
            )


class TestAgentMethods:
    """Tests for Agent methods."""

    def test_agent_claim_raises_not_implemented(self):
        """Test that claim method raises NotImplementedError."""
        agent = Agent(
            name="TestAgent",
            tags_with_elo={"python": 75},
            system_prompt="You are a test agent."
        )
        task = Task(description="stub", required_tags={"python": 50})

        with pytest.raises(NotImplementedError):
            agent.claim(task, client=None)

    def test_agent_execute_raises_not_implemented(self):
        """Test that execute method raises NotImplementedError."""
        agent = Agent(
            name="TestAgent",
            tags_with_elo={"python": 75},
            system_prompt="You are a test agent."
        )
        task = Task(description="stub", required_tags={"python": 50})

        with pytest.raises(NotImplementedError):
            agent.execute(task, client=None)
