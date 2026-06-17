"""Tests for the Agent class in the AAOSA core module."""

import pytest
from pydantic import ValidationError
from unittest.mock import MagicMock

from aaosa.core.agent import Agent
from aaosa.runtime.providers import LLMProvider
from aaosa.schemas.claim import Claim
from aaosa.schemas.task import Task
from aaosa.schemas.output import Output, LLMMetadata


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _provider_for_execute(content="answer", model="gpt-4o-mini"):
    provider = MagicMock(spec=LLMProvider)
    resp = MagicMock()
    resp.choices[0].message.content = content
    resp.choices[0].finish_reason = "stop"
    resp.model = model
    resp.usage.prompt_tokens = 10
    resp.usage.completion_tokens = 5
    provider.complete.return_value = resp
    return provider


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
    """Tests for Agent claim method — provider-based."""

    def test_claim_uses_provider_parse(self):
        """provider.parse is called; returned Claim has agent_id from self.id."""
        from aaosa.schemas.claim import Claim
        provider = MagicMock(spec=LLMProvider)
        provider.parse.return_value = Claim(
            agent_id="x", task_id="t", decision="claim", justification="j")
        agent = Agent(name="A", tags_with_elo={"python": 80}, system_prompt="p")
        task = Task(id="t", description="d", required_tags={"python": 50})
        claim = agent.claim(task, provider)
        assert isinstance(claim, Claim)
        assert claim.decision == "claim"
        assert claim.agent_id == agent.id  # depuis self.id, jamais la réponse LLM

    def test_claim_raises_when_provider_returns_none(self):
        """ValueError si provider.parse retourne None."""
        provider = MagicMock(spec=LLMProvider)
        provider.parse.return_value = None
        agent = Agent(name="A", tags_with_elo={"python": 80}, system_prompt="p")
        task = Task(id="t", description="d", required_tags={"python": 50})
        with pytest.raises(ValueError):
            agent.claim(task, provider)

    def test_claim_task_id_from_task(self):
        """task_id dans le Claim vient de task.id, pas de la réponse LLM."""
        provider = MagicMock(spec=LLMProvider)
        provider.parse.return_value = Claim(
            agent_id="irrelevant", task_id="irrelevant",
            decision="no_claim", justification="j")
        agent = Agent(name="A", tags_with_elo={"python": 80}, system_prompt="p")
        task = Task(description="do x", required_tags={"python": 50})
        result = agent.claim(task, provider)
        assert result.task_id == task.id
        assert result.agent_id == agent.id

    def test_claim_no_claim_decision(self):
        """decision='no_claim' est retourné fidèlement."""
        provider = MagicMock(spec=LLMProvider)
        provider.parse.return_value = Claim(
            agent_id="x", task_id="t", decision="no_claim", justification="out of scope")
        agent = Agent(name="A", tags_with_elo={"python": 80}, system_prompt="p")
        task = Task(description="do x", required_tags={"python": 50})
        result = agent.claim(task, provider)
        assert result.decision == "no_claim"


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

    @pytest.fixture
    def provider(self):
        """Create a mock LLMProvider with standard response."""
        return _provider_for_execute(content="Done!")

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

    def test_execute_returns_output_instance(self, agent, task, provider):
        """Test that execute returns an Output instance."""
        result = agent.execute(task, provider)
        assert isinstance(result, Output)

    def test_execute_output_task_id_matches(self, agent, task, provider):
        """Test that output task_id matches input task.id."""
        result = agent.execute(task, provider)
        assert result.task_id == task.id

    def test_execute_output_agent_id_matches(self, agent, task, provider):
        """Test that output agent_id matches agent.id."""
        result = agent.execute(task, provider)
        assert result.agent_id == agent.id

    def test_execute_output_content_from_llm(self, agent, task, provider):
        """Test that output content comes from LLM response."""
        result = agent.execute(task, provider)
        assert result.content == "Done!"

    def test_execute_llm_metadata_model_name(self, agent, task, provider):
        """Test that llm_metadata.model_name is set from response.model."""
        result = agent.execute(task, provider)
        assert result.llm_metadata.model_name == "gpt-4o-mini"

    def test_execute_llm_metadata_tokens_in(self, agent, task, provider):
        """Test that llm_metadata.tokens_in is set from response.usage.prompt_tokens."""
        result = agent.execute(task, provider)
        assert result.llm_metadata.tokens_in == 10

    def test_execute_llm_metadata_tokens_out(self, agent, task, provider):
        """Test that llm_metadata.tokens_out is set from response.usage.completion_tokens."""
        result = agent.execute(task, provider)
        assert result.llm_metadata.tokens_out == 5

    def test_execute_llm_metadata_latency_positive(self, agent, task, provider):
        """Test that llm_metadata.latency_ms is positive."""
        result = agent.execute(task, provider)
        assert result.llm_metadata.latency_ms > 0

    def test_execute_calls_provider_complete_once(self, agent, task, provider):
        """Test that provider.complete is called exactly once (no-tools path)."""
        agent.execute(task, provider)
        assert provider.complete.call_count == 1

    def test_execute_system_prompt_in_messages(self, agent, task, provider):
        """Test that agent.system_prompt is included in messages with role 'system'."""
        agent.execute(task, provider)
        call_args = provider.complete.call_args
        messages = call_args.kwargs.get("messages") or call_args.args[0]
        system_msgs = [m for m in messages if m.get("role") == "system"]
        assert any(agent.system_prompt in m["content"] for m in system_msgs)

    def test_execute_task_description_as_user_message(self, agent, task, provider):
        """Test that task.description is included in messages with role 'user'."""
        agent.execute(task, provider)
        call_args = provider.complete.call_args
        messages = call_args.kwargs.get("messages") or call_args.args[0]
        user_msgs = [m for m in messages if m.get("role") == "user"]
        assert any(task.description in m["content"] for m in user_msgs)

    def test_execute_passes_agent_model_to_provider(self):
        """provider.complete reçoit model=agent.model quand agent.model est défini."""
        provider = _provider_for_execute()
        agent = Agent(name="A", tags_with_elo={"python": 80}, system_prompt="p",
                      model="gpt-4o")
        task = Task(id="t", description="d", required_tags={"python": 50})
        agent.execute(task, provider)
        assert provider.complete.call_args.kwargs["model"] == "gpt-4o"

    def test_execute_model_none_when_no_agent_model(self, agent, task, provider):
        """provider.complete est appelé avec model=None quand agent.model est None."""
        agent.execute(task, provider)
        assert provider.complete.call_args.kwargs["model"] is None


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
