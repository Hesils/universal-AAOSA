"""Tests du roster incident — 7 agents / 3 domaines, tools résolus du YAML."""

from aaosa.core.agent import Agent
from aaosa.core.tool import ToolDef
from aaosa.demo.incident.agents import INCIDENT_AGENTS

_by_name = {a.name: a for a in INCIDENT_AGENTS}

EXPECTED_NAMES = {
    "backend-dev", "sre", "security-analyst", "dpo-jurist",
    "client-comm", "support-lead", "data-analyst",
}

EXPECTED_TOOLS = {
    "backend-dev": ["query_logs", "inspect_schema", "get_incident_report"],
    "sre": ["query_logs", "get_incident_report"],
    "security-analyst": ["query_logs", "lookup_cve", "get_incident_report"],
    "dpo-jurist": ["doc_search", "get_incident_report"],
    "client-comm": ["get_incident_report"],
    "support-lead": ["get_incident_report"],
    "data-analyst": ["count_affected_users", "query_logs", "inspect_schema"],
}


class TestRosterStructure:
    def test_seven_agents(self):
        assert len(INCIDENT_AGENTS) == 7

    def test_names(self):
        assert set(_by_name) == EXPECTED_NAMES

    def test_all_agent_instances_with_unique_ids(self):
        assert all(isinstance(a, Agent) for a in INCIDENT_AGENTS)
        ids = [a.id for a in INCIDENT_AGENTS]
        assert len(ids) == len(set(ids))

    def test_non_empty_system_prompts(self):
        assert all(a.system_prompt.strip() for a in INCIDENT_AGENTS)


class TestRosterTools:
    def test_tools_resolved_from_yaml(self):
        for name, expected in EXPECTED_TOOLS.items():
            tools = _by_name[name].tools
            assert all(isinstance(t, ToolDef) for t in tools)
            assert [t.name for t in tools] == expected


class TestRosterTags:
    def test_gdpr_monopoly(self):
        """Le dpo-jurist est seul sur les tags réglementaires → roster_gap quand absent."""
        for tag in ("gdpr", "legal", "compliance"):
            holders = [a.name for a in INCIDENT_AGENTS if tag in a.tags_with_elo]
            assert holders == ["dpo-jurist"], f"tag {tag} held by {holders}"

    def test_logs_competition(self):
        """Compétition intra-domaine : 3 agents d'ingénierie se disputent les logs."""
        holders = {a.name for a in INCIDENT_AGENTS if "logs" in a.tags_with_elo}
        assert holders == {"backend-dev", "sre", "security-analyst"}

    def test_communication_competition(self):
        holders = {a.name for a in INCIDENT_AGENTS if "communication" in a.tags_with_elo}
        assert holders == {"client-comm", "support-lead"}

    def test_database_overlap(self):
        holders = {a.name for a in INCIDENT_AGENTS if "database" in a.tags_with_elo}
        assert holders == {"backend-dev", "data-analyst"}
