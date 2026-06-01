import pytest

from aaosa.config.loader import load_agents
from aaosa.core.agent import Agent

VALID_YAML = """\
- name: Frontend
  tags_with_elo:
    frontend: 85
    css: 90
  system_prompt: "You are a frontend specialist."

- name: Backend
  tags_with_elo:
    backend: 90
    python: 80
  system_prompt: "You are a backend specialist."
"""


def _write(tmp_path, content, name="agents.yaml"):
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


class TestLoadAgents:
    def test_load_agents_valid(self, tmp_path):
        """A valid YAML file is parsed into a populated list[Agent]."""
        agents = load_agents(_write(tmp_path, VALID_YAML))

        assert isinstance(agents, list)
        assert len(agents) == 2
        assert all(isinstance(a, Agent) for a in agents)

        by_name = {a.name: a for a in agents}
        assert by_name["Frontend"].tags_with_elo == {"frontend": 85, "css": 90}
        assert by_name["Frontend"].system_prompt == "You are a frontend specialist."
        assert by_name["Backend"].tags_with_elo == {"backend": 90, "python": 80}

    def test_load_agents_missing_file(self, tmp_path):
        """A non-existent path raises ValueError."""
        with pytest.raises(ValueError):
            load_agents(tmp_path / "does_not_exist.yaml")

    def test_load_agents_malformed_yaml(self, tmp_path):
        """Syntactically invalid YAML raises ValueError."""
        bad = "- name: Frontend\n  tags_with_elo: {frontend: 85\n"  # unbalanced brace
        with pytest.raises(ValueError):
            load_agents(_write(tmp_path, bad))

    def test_load_agents_pydantic_invalid(self, tmp_path):
        """An entry violating the Agent schema raises ValueError."""
        invalid = """\
- name: Frontend
  tags_with_elo: {}
  system_prompt: "Empty tags are invalid."
"""
        with pytest.raises(ValueError):
            load_agents(_write(tmp_path, invalid))

    def test_load_agents_ids_unique(self, tmp_path):
        """Each loaded agent gets a unique generated id."""
        agents = load_agents(_write(tmp_path, VALID_YAML))
        ids = [a.id for a in agents]
        assert len(ids) == len(set(ids))

    def test_load_agents_empty_list(self, tmp_path):
        """An empty YAML list returns an empty list without error."""
        assert load_agents(_write(tmp_path, "[]")) == []
