from aaosa.core.agent import Agent
from aaosa.core.tool import ToolDef
from aaosa.demo.tools import (
    TOOLBOX,
    attach_tools,
    explain_query_plan,
    grep_codebase,
    read_file,
    run_tests,
)


def _agent(name: str) -> Agent:
    return Agent(name=name, tags_with_elo={"python": 80}, system_prompt="x")


class TestToolFns:
    def test_all_fns_return_str(self):
        assert isinstance(read_file(path="api/middleware.py"), str)
        assert isinstance(grep_codebase(pattern="SELECT"), str)
        assert isinstance(run_tests(path="tests/"), str)
        assert isinstance(explain_query_plan(sql="SELECT 1"), str)

    def test_toolbox_is_tooldefs(self):
        assert all(isinstance(t, ToolDef) for t in TOOLBOX.values())
        assert {"read_file", "grep_codebase", "run_tests", "explain_query_plan"} == set(TOOLBOX)


class TestAttachTools:
    def test_attaches_by_name(self):
        agents = [_agent("Backend"), _agent("Frontend"), _agent("Fullstack"), _agent("DevOps")]
        attach_tools(agents)
        by_name = {a.name: a for a in agents}
        assert {t.name for t in by_name["Backend"].tools} == {
            "read_file", "grep_codebase", "run_tests", "explain_query_plan"}
        assert {t.name for t in by_name["Frontend"].tools} == {"read_file", "grep_codebase"}
        assert {t.name for t in by_name["Fullstack"].tools} == {"read_file", "run_tests"}
        assert {t.name for t in by_name["DevOps"].tools} == {"read_file"}

    def test_unknown_agent_gets_no_tools(self):
        agents = [_agent("Unknown")]
        attach_tools(agents)
        assert agents[0].tools == []
