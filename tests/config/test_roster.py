import textwrap
from pathlib import Path

import pytest

from aaosa.config.roster import load_roster, load_rosters

AGENTS_YAML = textwrap.dedent("""\
    - name: alice
      tags_with_elo: {python: 1500}
      system_prompt: You are alice.
    - name: bob
      tags_with_elo: {ops: 1500}
      system_prompt: You are bob.
""")

TOOLS_PY = textwrap.dedent("""\
    from aaosa.core.tool import ToolDef
    TOOL_REGISTRY = {
        "echo": ToolDef(name="echo", description="echo", parameters={"type": "object", "properties": {}}, fn=lambda: "ok"),
    }
""")


def _write_roster(dir: Path, agents_yaml: str, tools_py: str | None = None) -> Path:
    dir.mkdir(parents=True, exist_ok=True)
    (dir / "agents.yaml").write_text(agents_yaml, encoding="utf-8")
    if tools_py is not None:
        (dir / "tools.py").write_text(tools_py, encoding="utf-8")
    return dir


def test_load_roster_without_tools(tmp_path):
    d = _write_roster(tmp_path / "r1", AGENTS_YAML)
    agents = load_roster(d)
    assert {a.name for a in agents} == {"alice", "bob"}


def test_load_roster_resolves_tools_from_tool_registry(tmp_path):
    yaml = AGENTS_YAML + textwrap.dedent("""\
        - name: carol
          tags_with_elo: {python: 1500}
          system_prompt: You are carol.
          tools: [echo]
    """)
    d = _write_roster(tmp_path / "r2", yaml, TOOLS_PY)
    agents = load_roster(d)
    carol = next(a for a in agents if a.name == "carol")
    assert [t.name for t in carol.tools] == ["echo"]


def test_load_roster_missing_agents_yaml_raises(tmp_path):
    d = tmp_path / "empty"
    d.mkdir()
    with pytest.raises(ValueError, match="agents.yaml"):
        load_roster(d)


def test_load_roster_tools_declared_without_tools_py_raises(tmp_path):
    yaml = textwrap.dedent("""\
        - name: dan
          tags_with_elo: {python: 1500}
          system_prompt: You are dan.
          tools: [missing]
    """)
    d = _write_roster(tmp_path / "r3", yaml)  # no tools.py
    with pytest.raises(ValueError):
        load_roster(d)


def test_load_roster_bad_tool_registry_type_raises(tmp_path):
    bad = "TOOL_REGISTRY = ['not', 'a', 'dict']\n"
    d = _write_roster(tmp_path / "r4", AGENTS_YAML, bad)
    with pytest.raises(ValueError, match="TOOL_REGISTRY"):
        load_roster(d)


def test_load_rosters_merges_and_detects_name_collision(tmp_path):
    a = _write_roster(tmp_path / "ra", AGENTS_YAML)
    b = _write_roster(tmp_path / "rb", "- name: alice\n  tags_with_elo: {x: 1500}\n  system_prompt: dup\n")
    with pytest.raises(ValueError, match="collision"):
        load_rosters([a, b])


def test_load_rosters_empty_list_raises(tmp_path):
    with pytest.raises(ValueError, match="at least one"):
        load_rosters([])
