import pytest
from datetime import datetime, timezone
from pathlib import Path
from aaosa.elo.persistence import (
    AgentEloSnapshot,
    EloSnapshot,
    save_snapshot,
    load_snapshot,
    apply_snapshot,
)
from aaosa.core.agent import Agent


def make_agent(name: str, tags: dict[str, int]) -> Agent:
    return Agent(name=name, tags_with_elo=tags, system_prompt="test")


class TestAgentEloSnapshot:
    def test_valid_snapshot(self):
        s = AgentEloSnapshot(
            agent_name="Frontend",
            agent_id="uuid-1",
            tags_with_elo={"css": 85, "javascript": 80},
        )
        assert s.agent_name == "Frontend"

    def test_json_roundtrip(self):
        s = AgentEloSnapshot(
            agent_name="Backend",
            agent_id="uuid-2",
            tags_with_elo={"python": 90},
        )
        data = s.model_dump_json()
        s2 = AgentEloSnapshot.model_validate_json(data)
        assert s2.agent_name == s.agent_name
        assert s2.tags_with_elo == s.tags_with_elo


class TestEloSnapshot:
    def test_valid_snapshot(self):
        snap = EloSnapshot(
            timestamp=datetime.now(timezone.utc),
            agents=[
                AgentEloSnapshot(agent_name="A", agent_id="1", tags_with_elo={"x": 50}),
            ],
        )
        assert len(snap.agents) == 1

    def test_empty_agents_list(self):
        snap = EloSnapshot(
            timestamp=datetime.now(timezone.utc),
            agents=[],
        )
        assert snap.agents == []


class TestSaveSnapshot:
    def test_save_creates_latest_json(self, tmp_path):
        agents = [make_agent("A", {"python": 50})]
        save_snapshot(agents, tmp_path)
        assert (tmp_path / "latest.json").exists()

    def test_save_creates_timestamped_file(self, tmp_path):
        agents = [make_agent("A", {"python": 50})]
        path = save_snapshot(agents, tmp_path)
        assert path.exists()
        assert path.name != "latest.json"

    def test_save_latest_matches_timestamped(self, tmp_path):
        agents = [make_agent("A", {"python": 50})]
        path = save_snapshot(agents, tmp_path)
        latest_content = (tmp_path / "latest.json").read_text(encoding="utf-8")
        timestamped_content = path.read_text(encoding="utf-8")
        assert latest_content == timestamped_content

    def test_save_multiple_agents(self, tmp_path):
        agents = [
            make_agent("A", {"python": 50}),
            make_agent("B", {"css": 80, "js": 60}),
        ]
        save_snapshot(agents, tmp_path)
        snap = load_snapshot(tmp_path / "latest.json")
        assert len(snap.agents) == 2

    def test_save_returns_path(self, tmp_path):
        agents = [make_agent("A", {"python": 50})]
        result = save_snapshot(agents, tmp_path)
        assert isinstance(result, Path)


class TestLoadSnapshot:
    def test_load_roundtrip(self, tmp_path):
        agents = [make_agent("A", {"python": 50, "backend": 80})]
        save_snapshot(agents, tmp_path)
        snap = load_snapshot(tmp_path / "latest.json")
        assert len(snap.agents) == 1
        assert snap.agents[0].agent_name == "A"
        assert snap.agents[0].tags_with_elo == {"python": 50, "backend": 80}

    def test_load_nonexistent_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_snapshot(tmp_path / "nope.json")


class TestApplySnapshot:
    def test_apply_restores_elo(self, tmp_path):
        """Save -> modify agent -> apply -> ELO restored."""
        agent = make_agent("A", {"python": 50})
        save_snapshot([agent], tmp_path)
        agent.tags_with_elo["python"] = 99
        snap = load_snapshot(tmp_path / "latest.json")
        apply_snapshot([agent], snap)
        assert agent.tags_with_elo["python"] == 50

    def test_apply_matches_by_name_not_id(self):
        """Agents with same name but different IDs should match."""
        agent1 = make_agent("A", {"python": 50})
        snap = EloSnapshot(
            timestamp=datetime.now(timezone.utc),
            agents=[AgentEloSnapshot(
                agent_name="A",
                agent_id="different-uuid",
                tags_with_elo={"python": 80},
            )],
        )
        apply_snapshot([agent1], snap)
        assert agent1.tags_with_elo["python"] == 80

    def test_apply_agent_not_in_snapshot_untouched(self):
        """Agent absent from snapshot should not be modified."""
        agent = make_agent("B", {"css": 60})
        snap = EloSnapshot(
            timestamp=datetime.now(timezone.utc),
            agents=[AgentEloSnapshot(
                agent_name="A", agent_id="1", tags_with_elo={"python": 80},
            )],
        )
        apply_snapshot([agent], snap)
        assert agent.tags_with_elo == {"css": 60}

    def test_apply_snapshot_agent_absent_from_list_ignored(self):
        """Snapshot agent absent from agents list should be silently ignored."""
        agent = make_agent("A", {"python": 50})
        snap = EloSnapshot(
            timestamp=datetime.now(timezone.utc),
            agents=[
                AgentEloSnapshot(agent_name="A", agent_id="1", tags_with_elo={"python": 80}),
                AgentEloSnapshot(agent_name="Ghost", agent_id="2", tags_with_elo={"x": 10}),
            ],
        )
        apply_snapshot([agent], snap)
        assert agent.tags_with_elo["python"] == 80

    def test_apply_duplicate_agent_names_raises(self):
        """Duplicate names in agents list should raise ValueError."""
        a1 = make_agent("A", {"python": 50})
        a2 = make_agent("A", {"css": 60})
        snap = EloSnapshot(
            timestamp=datetime.now(timezone.utc),
            agents=[],
        )
        with pytest.raises(ValueError, match="duplicate"):
            apply_snapshot([a1, a2], snap)

    def test_apply_overwrites_all_tags(self):
        """apply_snapshot replaces the entire tags_with_elo dict, not just shared keys."""
        agent = make_agent("A", {"python": 50, "css": 30})
        snap = EloSnapshot(
            timestamp=datetime.now(timezone.utc),
            agents=[AgentEloSnapshot(
                agent_name="A", agent_id="1",
                tags_with_elo={"python": 80, "docker": 40},
            )],
        )
        apply_snapshot([agent], snap)
        assert agent.tags_with_elo == {"python": 80, "docker": 40}
