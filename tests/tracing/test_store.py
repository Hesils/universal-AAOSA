from pathlib import Path

from aaosa.core.agent import Agent
from aaosa.tracing.store import (
    AgentRegistry,
    AgentRegistryEntry,
    new_session_id,
    save_agent_registry,
)


def make_agent(name: str, tags: dict[str, int]) -> Agent:
    return Agent(name=name, tags_with_elo=tags, system_prompt=f"prompt for {name}")


class TestNewSessionId:
    def test_is_unique(self):
        ids = {new_session_id() for _ in range(50)}
        assert len(ids) == 50

    def test_is_sortable_string(self):
        sid = new_session_id()
        assert isinstance(sid, str)
        # forme: 2026-05-29T14-30-00-ab12
        assert sid[:4].isdigit()
        assert "T" in sid


class TestSaveAgentRegistry:
    def test_writes_file(self, tmp_path):
        agents = [make_agent("Frontend", {"css": 80})]
        path = save_agent_registry(agents, tmp_path / "agents" / "registry.json")
        assert path.exists()

    def test_creates_parent_dirs(self, tmp_path):
        agents = [make_agent("Frontend", {"css": 80})]
        save_agent_registry(agents, tmp_path / "agents" / "registry.json")
        assert (tmp_path / "agents").is_dir()

    def test_roundtrip(self, tmp_path):
        agents = [
            make_agent("Frontend", {"css": 80, "javascript": 70}),
            make_agent("Backend", {"python": 90}),
        ]
        path = save_agent_registry(agents, tmp_path / "registry.json")
        reg = AgentRegistry.model_validate_json(path.read_text(encoding="utf-8"))
        assert len(reg.agents) == 2
        fe = next(e for e in reg.agents if e.name == "Frontend")
        assert fe.tags_with_elo == {"css": 80, "javascript": 70}
        assert fe.system_prompt == "prompt for Frontend"
        assert fe.agent_id == agents[0].id

    def test_entry_rejects_extra_field(self):
        import pytest
        with pytest.raises(Exception):
            AgentRegistryEntry(
                agent_id="1", name="X", system_prompt="p",
                tags_with_elo={"a": 1}, bogus="bad",
            )
