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
from dashboard.graph_model import _build_nodes, _build_edges, _tool_node_id

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
