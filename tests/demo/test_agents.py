import pytest
from aaosa.core.agent import Agent
from aaosa.demo.agents import (
    AGENT_FRONTEND,
    AGENT_BACKEND,
    AGENT_DEVOPS,
    AGENT_FULLSTACK,
    DEMO_AGENTS,
)


class TestAgentInstanceTypes:
    """Tests that all agent constants are Agent instances."""

    def test_agent_frontend_is_agent_instance(self):
        """AGENT_FRONTEND should be an Agent instance."""
        assert isinstance(AGENT_FRONTEND, Agent)

    def test_agent_backend_is_agent_instance(self):
        """AGENT_BACKEND should be an Agent instance."""
        assert isinstance(AGENT_BACKEND, Agent)

    def test_agent_devops_is_agent_instance(self):
        """AGENT_DEVOPS should be an Agent instance."""
        assert isinstance(AGENT_DEVOPS, Agent)

    def test_agent_fullstack_is_agent_instance(self):
        """AGENT_FULLSTACK should be an Agent instance."""
        assert isinstance(AGENT_FULLSTACK, Agent)


class TestAgentTags:
    """Tests for agent tags_with_elo specifications."""

    def test_agent_frontend_tags(self):
        """AGENT_FRONTEND should have correct tags and ELO values."""
        expected = {"frontend": 85, "css": 90, "javascript": 80, "testing": 40}
        assert AGENT_FRONTEND.tags_with_elo == expected

    def test_agent_backend_tags(self):
        """AGENT_BACKEND should have correct tags and ELO values."""
        expected = {"backend": 90, "database": 85, "python": 80, "testing": 50}
        assert AGENT_BACKEND.tags_with_elo == expected

    def test_agent_devops_tags(self):
        """AGENT_DEVOPS should have correct tags and ELO values."""
        expected = {"infrastructure": 90, "docker": 85, "ci_cd": 80, "backend": 30}
        assert AGENT_DEVOPS.tags_with_elo == expected

    def test_agent_fullstack_tags(self):
        """AGENT_FULLSTACK should have correct tags and ELO values."""
        expected = {"frontend": 50, "backend": 55, "javascript": 60, "python": 50, "database": 40}
        assert AGENT_FULLSTACK.tags_with_elo == expected


class TestDemoAgentsList:
    """Tests for DEMO_AGENTS list structure and content."""

    def test_demo_agents_is_list(self):
        """DEMO_AGENTS should be a list."""
        assert isinstance(DEMO_AGENTS, list)

    def test_demo_agents_contains_four_agents(self):
        """DEMO_AGENTS should contain exactly 4 agents."""
        assert len(DEMO_AGENTS) == 4

    def test_demo_agents_all_agent_instances(self):
        """All elements in DEMO_AGENTS should be Agent instances."""
        for agent in DEMO_AGENTS:
            assert isinstance(agent, Agent)

    def test_demo_agents_contains_frontend(self):
        """DEMO_AGENTS should contain AGENT_FRONTEND."""
        assert AGENT_FRONTEND in DEMO_AGENTS

    def test_demo_agents_contains_backend(self):
        """DEMO_AGENTS should contain AGENT_BACKEND."""
        assert AGENT_BACKEND in DEMO_AGENTS


class TestAgentSystemPrompts:
    """Tests for agent system_prompt properties."""

    def test_all_agents_have_non_empty_system_prompt(self):
        """All agents (including DEMO_AGENTS) should have non-empty system_prompt."""
        all_agents = [AGENT_FRONTEND, AGENT_BACKEND, AGENT_DEVOPS, AGENT_FULLSTACK]
        for agent in all_agents:
            assert isinstance(agent.system_prompt, str)
            assert len(agent.system_prompt) > 0


class TestAgentIds:
    """Tests for agent ID uniqueness."""

    def test_all_agent_ids_unique(self):
        """All agent IDs in DEMO_AGENTS should be unique."""
        ids = [agent.id for agent in DEMO_AGENTS]
        assert len(ids) == len(set(ids))
