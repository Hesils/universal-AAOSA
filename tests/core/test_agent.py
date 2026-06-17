"""Tests for the Agent class in the AAOSA core module."""

import pytest
from pydantic import ValidationError
from unittest.mock import MagicMock
from openai import OpenAI

from aaosa.core.agent import Agent
from aaosa.schemas.claim import Claim
from aaosa.schemas.task import Task
from aaosa.schemas.output import Output, LLMMetadata


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

    def test_agent_claim_returns_claim(self):
        """Test that claim returns a Claim with agent_id and task_id overridden from self."""
        agent = Agent(
            name="TestAgent",
            tags_with_elo={"python": 75},
            system_prompt="You are a test agent."
        )
        task = Task(description="Write a Python function", required_tags={"python": 50})

        # Build a fake parsed Claim (LLM would return wrong ids — override must happen)
        fake_claim = Claim(
            agent_id="irrelevant",
            task_id="irrelevant",
            decision="claim",
            justification="test justification",
        )

        # Mock the structured output path
        mock_parsed_response = MagicMock()
        mock_parsed_response.choices[0].message.parsed = fake_claim

        client = MagicMock(spec=OpenAI)
        client.beta.chat.completions.parse.return_value = mock_parsed_response

        result = agent.claim(task, client)

        assert isinstance(result, Claim)
        assert result.agent_id == agent.id  # override must have happened
        assert result.task_id == task.id    # override must have happened
        assert result.decision in ("claim", "no_claim")

    def test_agent_claim_uses_fallback_when_parsed_is_none(self):
        """Test that claim falls back to JSON parse when structured output returns parsed=None."""
        agent = Agent(
            name="TestAgent",
            tags_with_elo={"python": 75},
            system_prompt="You are a test agent."
        )
        task = Task(description="Write a Python function", required_tags={"python": 50})

        client = MagicMock(spec=OpenAI)

        # Structured output path returns parsed=None
        mock_parse_response = MagicMock()
        mock_parse_response.choices[0].message.parsed = None
        client.beta.chat.completions.parse.return_value = mock_parse_response

        # Fallback path returns valid JSON
        mock_create_response = MagicMock()
        mock_create_response.choices[0].message.content = '{"decision": "no_claim", "justification": "Out of scope"}'
        client.chat.completions.create.return_value = mock_create_response

        result = agent.claim(task, client)

        assert isinstance(result, Claim)
        assert result.decision == "no_claim"
        assert result.agent_id == agent.id
        assert result.task_id == task.id

    def test_agent_claim_uses_fallback_when_parse_raises(self):
        """Test that claim falls back to JSON parse when structured output raises an exception."""
        agent = Agent(
            name="TestAgent",
            tags_with_elo={"python": 75},
            system_prompt="You are a test agent."
        )
        task = Task(description="Write a Python function", required_tags={"python": 50})

        client = MagicMock(spec=OpenAI)

        # Structured output path raises
        client.beta.chat.completions.parse.side_effect = RuntimeError("unsupported")

        # Fallback path returns valid JSON
        mock_create_response = MagicMock()
        mock_create_response.choices[0].message.content = '{"decision": "claim", "justification": "I can do it"}'
        client.chat.completions.create.return_value = mock_create_response

        result = agent.claim(task, client)

        assert isinstance(result, Claim)
        assert result.decision == "claim"
        assert result.agent_id == agent.id


class TestAgentEdgeCases:
    """Edge case tests for Agent schema."""

    def test_agent_id_is_uuid_format(self):
        """agent.id has len 36 and 4 tirets."""
        agent = Agent(
            name="TestAgent",
            tags_with_elo={"python": 75},
            system_prompt="You are a test agent."
        )
        assert len(agent.id) == 36
        assert agent.id.count("-") == 4

    def test_agent_tags_with_elo_values_are_ints(self):
        """All values in tags_with_elo are int."""
        agent = Agent(
            name="TestAgent",
            tags_with_elo={"python": 75, "ml": 60, "devops": 50},
            system_prompt="You are a test agent."
        )
        for value in agent.tags_with_elo.values():
            assert isinstance(value, int)

    def test_agent_single_tag_valid(self):
        """tags_with_elo={'python': 1} is valid."""
        agent = Agent(
            name="TestAgent",
            tags_with_elo={"python": 1},
            system_prompt="You are a test agent."
        )
        assert agent.tags_with_elo == {"python": 1}


class TestAgentExecute:
    """Tests for Agent.execute method."""

    def make_mock_client(self):
        """Create a mock LLM client with standard response."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices[0].message.content = "Done!"
        mock_response.model = "gpt-4o-mini"
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 5
        mock_client.chat.completions.create.return_value = mock_response
        return mock_client

    @pytest.fixture
    def agent(self):
        """Create a test agent."""
        return Agent(
            name="TestAgent",
            tags_with_elo={"python": 80},
            system_prompt="You are a Python expert."
        )

    @pytest.fixture
    def task(self):
        """Create a test task."""
        return Task(description="Write a sorting function", required_tags={"python": 50})

    def test_execute_returns_output_instance(self, agent, task):
        """Test that execute returns an Output instance."""
        mock_client = self.make_mock_client()
        result = agent.execute(task, mock_client)
        assert isinstance(result, Output)

    def test_execute_output_task_id_matches(self, agent, task):
        """Test that output task_id matches input task.id."""
        mock_client = self.make_mock_client()
        result = agent.execute(task, mock_client)
        assert result.task_id == task.id

    def test_execute_output_agent_id_matches(self, agent, task):
        """Test that output agent_id matches agent.id."""
        mock_client = self.make_mock_client()
        result = agent.execute(task, mock_client)
        assert result.agent_id == agent.id

    def test_execute_output_content_from_llm(self, agent, task):
        """Test that output content comes from LLM response."""
        mock_client = self.make_mock_client()
        result = agent.execute(task, mock_client)
        assert result.content == "Done!"

    def test_execute_llm_metadata_model_name(self, agent, task):
        """Test that llm_metadata.model_name is set from response.model."""
        mock_client = self.make_mock_client()
        result = agent.execute(task, mock_client)
        assert result.llm_metadata.model_name == "gpt-4o-mini"

    def test_execute_llm_metadata_tokens_in(self, agent, task):
        """Test that llm_metadata.tokens_in is set from response.usage.prompt_tokens."""
        mock_client = self.make_mock_client()
        result = agent.execute(task, mock_client)
        assert result.llm_metadata.tokens_in == 10

    def test_execute_llm_metadata_tokens_out(self, agent, task):
        """Test that llm_metadata.tokens_out is set from response.usage.completion_tokens."""
        mock_client = self.make_mock_client()
        result = agent.execute(task, mock_client)
        assert result.llm_metadata.tokens_out == 5

    def test_execute_llm_metadata_latency_positive(self, agent, task):
        """Test that llm_metadata.latency_ms is positive."""
        mock_client = self.make_mock_client()
        result = agent.execute(task, mock_client)
        assert result.llm_metadata.latency_ms > 0

    def test_execute_calls_client_once(self, agent, task):
        """Test that client.chat.completions.create is called exactly once."""
        mock_client = self.make_mock_client()
        agent.execute(task, mock_client)
        assert mock_client.chat.completions.create.call_count == 1

    def test_execute_system_prompt_in_messages(self, agent, task):
        """Test that agent.system_prompt is included in messages with role 'system'."""
        mock_client = self.make_mock_client()
        agent.execute(task, mock_client)
        call_args = mock_client.chat.completions.create.call_args
        messages = call_args.kwargs.get("messages") or (call_args.args[0] if call_args.args else call_args.kwargs["messages"])
        system_msgs = [m for m in messages if m.get("role") == "system"]
        assert any(agent.system_prompt in m["content"] for m in system_msgs)

    def test_execute_task_description_as_user_message(self, agent, task):
        """Test that task.description is included in messages with role 'user'."""
        mock_client = self.make_mock_client()
        agent.execute(task, mock_client)
        call_args = mock_client.chat.completions.create.call_args
        messages = call_args.kwargs.get("messages") or (call_args.args[0] if call_args.args else call_args.kwargs["messages"])
        user_msgs = [m for m in messages if m.get("role") == "user"]
        assert any(task.description in m["content"] for m in user_msgs)


class TestAgentProviderModel:
    def test_provider_and_model_default_to_none(self):
        a = Agent(name="A", tags_with_elo={"x": 50}, system_prompt="p")
        assert a.provider is None
        assert a.model is None

    def test_provider_and_model_can_be_set(self):
        a = Agent(name="A", tags_with_elo={"x": 50}, system_prompt="p",
                  provider="ollama", model="llama3.1")
        assert a.provider == "ollama"
        assert a.model == "llama3.1"


class TestBuildUserContent:
    """Tests for Agent._build_user_content method."""

    def test_build_user_content_uses_task_context(self):
        """Test that _build_user_content includes task.context when present."""
        agent = Agent(name="a", tags_with_elo={"python": 50}, system_prompt="sp")
        task = Task(description="do x", required_tags={"python": 50}, context="DOMAIN CTX")
        content = agent._build_user_content(task)
        assert "DOMAIN CTX" in content

    def test_build_user_content_falls_back_to_metadata_context(self):
        """Test that _build_user_content falls back to metadata['context'] when task.context is None."""
        agent = Agent(name="a", tags_with_elo={"python": 50}, system_prompt="sp")
        task = Task(description="do x", required_tags={"python": 50}, metadata={"context": "META CTX"})
        content = agent._build_user_content(task)
        assert "META CTX" in content
