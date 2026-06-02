from aaosa.tracing.events import (
    DividedSubTask,
    ExecutedEvent,
    Phase1FilteredEvent,
    Phase2ClaimedEvent,
    DispatchedEvent,
    QAEvaluatedEvent,
    TaskAggregatedEvent,
    TaskDividedEvent,
    ToolCalledEvent,
)
from aaosa.tracing.store import SessionMeta, SessionTaskRecord
from dashboard.graph_model import _build_nodes, _build_edges, _tool_node_id, build_graph

SID = "s"


def _tool(tid, aid, name):
    return ToolCalledEvent(session_id=SID, task_id=tid, agent_id=aid, tool_name=name, arguments={}, result="r", latency_ms=0.1)


class TestNodes:
    def test_base_nodes_present(self):
        nodes = _build_nodes([])
        ids = {n.id for n in nodes}
        assert {"input", "dispatch", "evaluator", "output", "testset"} <= ids

    def test_tool_nodes_from_distinct_tool_names(self):
        events = [_tool("t1", "ag", "grep"), _tool("t1", "ag", "grep"), _tool("t1", "ag", "read")]
        nodes = _build_nodes(events)
        tool_nodes = [n for n in nodes if n.type == "tool"]
        assert {n.id for n in tool_nodes} == {_tool_node_id("grep"), _tool_node_id("read")}
        assert all(n.layer == "tools" for n in tool_nodes)
        assert {n.label for n in tool_nodes} == {"grep", "read"}

    def test_divider_aggregator_nodes_only_when_divided(self):
        assert "divider" not in {n.id for n in _build_nodes([])}
        divided = [TaskDividedEvent(session_id=SID, task_id="p", sub_tasks=[DividedSubTask(id="s1", description="x")])]
        ids = {n.id for n in _build_nodes(divided)}
        assert "divider" in ids and "aggregator" in ids


class TestEdges:
    def test_agent_tool_edges(self):
        events = [_tool("t1", "ag", "grep")]
        nodes = _build_nodes(events)
        edges = _build_edges(nodes, events)
        pairs = {(e.from_node, e.to) for e in edges}
        assert ("ag", _tool_node_id("grep")) in pairs

    def test_divider_backbone_edges(self):
        divided = [TaskDividedEvent(session_id=SID, task_id="p", sub_tasks=[DividedSubTask(id="s1", description="x")])]
        nodes = _build_nodes(divided)
        edges = _build_edges(nodes, divided)
        pairs = {(e.from_node, e.to) for e in edges}
        assert ("input", "divider") in pairs
        assert ("divider", "aggregator") in pairs
        assert ("aggregator", "output") in pairs


def _meta(task_id, desc, tags=None):
    return SessionMeta(
        session_id=SID, started_at="2026-01-01T00:00:00Z", ended_at="2026-01-01T00:01:00Z",
        tasks=[SessionTaskRecord(id=task_id, description=desc, winner_agent_id=None, outcome="qa_pass", required_tags=tags or {})],
        agent_ids=["ag"],
    )


def _simple_run(tid="t1", aid="ag", success=True):
    return [
        Phase1FilteredEvent(session_id=SID, task_id=tid, agent_id=aid, passed=True, fit_score=0.9),
        Phase2ClaimedEvent(session_id=SID, task_id=tid, agent_id=aid, decision="claim", justification="mine"),
        DispatchedEvent(session_id=SID, task_id=tid, agent_id=aid, reason="sole claimer"),
        ExecutedEvent(session_id=SID, task_id=tid, agent_id=aid, output_summary="sum", output_content="content"),
        QAEvaluatedEvent(session_id=SID, task_id=tid, agent_id=aid, success=success, score=1.0 if success else 0.0, reason="r"),
    ]


class TestSimpleRunMilestones:
    def test_milestone_sequence(self):
        graph = build_graph(_simple_run(), _meta("t1", "do it"))
        assert [s.milestone_type for s in graph.steps] == ["input", "dispatch", "agent", "evaluator", "output"]

    def test_input_milestone_synthesized_from_meta(self):
        graph = build_graph(_simple_run(), _meta("t1", "do it", {"backend": 70}))
        inp = graph.steps[0]
        assert inp.active_nodes == ["input"]
        assert inp.detail.input.description == "do it"
        assert inp.detail.input.required_tags == {"backend": 70}

    def test_dispatch_milestone_lights_input_dispatch_and_winner(self):
        graph = build_graph(_simple_run(), _meta("t1", "do it"))
        disp_step = next(s for s in graph.steps if s.milestone_type == "dispatch")
        assert "dispatch" in disp_step.active_nodes and "ag" in disp_step.active_nodes
        pairs = {(e.from_node, e.to) for e in disp_step.active_edges}
        assert ("input", "dispatch") in pairs   # backbone
        assert ("dispatch", "ag") in pairs       # fan-out
        assert disp_step.winner_agent_id == "ag"

    def test_agent_milestone_carries_output(self):
        graph = build_graph(_simple_run(), _meta("t1", "do it"))
        agent_step = next(s for s in graph.steps if s.milestone_type == "agent")
        assert agent_step.active_nodes == ["ag"]
        assert agent_step.detail.agents["ag"].output_content == "content"

    def test_evaluator_milestone_pass(self):
        graph = build_graph(_simple_run(success=True), _meta("t1", "do it"))
        ev = next(s for s in graph.steps if s.milestone_type == "evaluator")
        assert ev.outcome == "qa_pass"
        assert "evaluator" in ev.active_nodes
        pairs = {(e.from_node, e.to) for e in ev.active_edges}
        assert ("ag", "evaluator") in pairs

    def test_output_milestone_backbone_persists(self):
        graph = build_graph(_simple_run(), _meta("t1", "do it"))
        out = graph.steps[-1]
        assert out.milestone_type == "output"
        assert "output" in out.active_nodes
        pairs = {(e.from_node, e.to) for e in out.active_edges}
        assert ("input", "dispatch") in pairs   # backbone cumulatif toujours présent
        assert ("evaluator", "output") in pairs
        assert out.detail.output.output_content == "content"
