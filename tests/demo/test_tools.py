from aaosa.core.tool import ToolDef
from aaosa.demo.agents import DEMO_AGENTS
from aaosa.demo.tools import (
    TOOLBOX,
    explain_query_plan,
    grep_codebase,
    read_file,
    run_tests,
)


class TestToolFns:
    def test_all_fns_return_str(self):
        assert isinstance(read_file(path="api/middleware.py"), str)
        assert isinstance(grep_codebase(pattern="SELECT"), str)
        assert isinstance(run_tests(path="tests/"), str)
        assert isinstance(explain_query_plan(sql="SELECT 1"), str)

    def test_toolbox_is_tooldefs(self):
        assert all(isinstance(t, ToolDef) for t in TOOLBOX.values())
        assert {"read_file", "grep_codebase", "run_tests", "explain_query_plan"} == set(TOOLBOX)


class TestDemoAgentsTools:
    def test_demo_agents_carry_yaml_tools(self):
        """DEMO_AGENTS porte les tools déclarés dans agents.yaml (résolution loader)."""
        by_name = {a.name: a for a in DEMO_AGENTS}
        assert {t.name for t in by_name["Backend"].tools} == {
            "read_file", "grep_codebase", "run_tests", "explain_query_plan"}
        assert {t.name for t in by_name["Frontend"].tools} == {"read_file", "grep_codebase"}
        assert {t.name for t in by_name["Fullstack"].tools} == {"read_file", "run_tests"}
        assert {t.name for t in by_name["DevOps"].tools} == {"read_file"}

    def test_demo_agents_tools_are_toolbox_instances(self):
        """Les ToolDef attachés sont ceux du TOOLBOX (pas des copies)."""
        by_name = {a.name: a for a in DEMO_AGENTS}
        for tool in by_name["Backend"].tools:
            assert tool is TOOLBOX[tool.name]
