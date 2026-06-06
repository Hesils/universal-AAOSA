import pytest

from aaosa.config.loader import load_agents
from aaosa.core.agent import Agent
from aaosa.core.tool import ToolDef

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


def _tooldef(name: str) -> ToolDef:
    return ToolDef(
        name=name,
        description=f"{name} tool",
        parameters={"type": "object", "properties": {}},
        fn=lambda: "ok",
    )


REGISTRY = {
    "read_file": _tooldef("read_file"),
    "grep_codebase": _tooldef("grep_codebase"),
}

TOOLS_YAML = """\
- name: Backend
  tags_with_elo:
    backend: 90
  system_prompt: "You are a backend specialist."
  tools: [read_file, grep_codebase]

- name: Frontend
  tags_with_elo:
    frontend: 85
  system_prompt: "You are a frontend specialist."
"""

MINIMAL_ENTRY = """\
- name: A
  tags_with_elo: {python: 50}
  system_prompt: "x"
"""


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


class TestLoadAgentsTools:
    def test_tools_resolved_from_registry(self, tmp_path):
        """Les noms YAML sont résolus en ToolDef du registry, ordre préservé."""
        agents = load_agents(_write(tmp_path, TOOLS_YAML), tool_registry=REGISTRY)
        by_name = {a.name: a for a in agents}
        assert [t.name for t in by_name["Backend"].tools] == ["read_file", "grep_codebase"]
        assert by_name["Backend"].tools[0] is REGISTRY["read_file"]

    def test_entry_without_tools_gets_empty_list(self, tmp_path):
        """Une entrée sans champ tools → tools=[] même avec registry fourni."""
        agents = load_agents(_write(tmp_path, TOOLS_YAML), tool_registry=REGISTRY)
        by_name = {a.name: a for a in agents}
        assert by_name["Frontend"].tools == []

    def test_retrocompat_no_registry_no_tools(self, tmp_path):
        """YAML sans tools + pas de registry → comportement V3-A1 intact."""
        agents = load_agents(_write(tmp_path, VALID_YAML))
        assert all(a.tools == [] for a in agents)

    def test_unknown_tool_name_raises(self, tmp_path):
        """Nom absent du registry → ValueError nommant tool + agent + disponibles."""
        yaml_txt = TOOLS_YAML.replace("grep_codebase", "does_not_exist")
        with pytest.raises(ValueError, match="does_not_exist") as exc_info:
            load_agents(_write(tmp_path, yaml_txt), tool_registry=REGISTRY)
        assert "Backend" in str(exc_info.value)
        assert "read_file" in str(exc_info.value)  # noms disponibles listés

    def test_tools_declared_without_registry_raises(self, tmp_path):
        """tools non vide dans le YAML mais tool_registry=None → ValueError."""
        with pytest.raises(ValueError, match="tool_registry"):
            load_agents(_write(tmp_path, TOOLS_YAML))

    def test_empty_tools_list_ok_without_registry(self, tmp_path):
        """tools: [] explicite → tools=[], pas d'erreur même sans registry."""
        yaml_txt = MINIMAL_ENTRY.replace('system_prompt: "x"', 'system_prompt: "x"\n  tools: []')
        agents = load_agents(_write(tmp_path, yaml_txt))
        assert agents[0].tools == []

    def test_tools_not_a_list_raises(self, tmp_path):
        """tools: read_file (scalaire) → ValueError."""
        yaml_txt = MINIMAL_ENTRY.replace('system_prompt: "x"', 'system_prompt: "x"\n  tools: read_file')
        with pytest.raises(ValueError, match="list of strings"):
            load_agents(_write(tmp_path, yaml_txt), tool_registry=REGISTRY)

    def test_tools_non_str_items_raises(self, tmp_path):
        """tools: [1, 2] → ValueError."""
        yaml_txt = MINIMAL_ENTRY.replace('system_prompt: "x"', 'system_prompt: "x"\n  tools: [1, 2]')
        with pytest.raises(ValueError, match="list of strings"):
            load_agents(_write(tmp_path, yaml_txt), tool_registry=REGISTRY)

    def test_duplicate_tool_names_raises(self, tmp_path):
        """Doublon dans tools → ValueError."""
        yaml_txt = MINIMAL_ENTRY.replace(
            'system_prompt: "x"', 'system_prompt: "x"\n  tools: [read_file, read_file]'
        )
        with pytest.raises(ValueError, match="duplicate"):
            load_agents(_write(tmp_path, yaml_txt), tool_registry=REGISTRY)
