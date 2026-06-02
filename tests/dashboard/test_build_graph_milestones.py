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
    UnassignedEvent,
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


class TestToolMilestones:
    def _run_with_tools(self, names):
        tid, aid = "t1", "ag"
        evs = [
            Phase1FilteredEvent(session_id=SID, task_id=tid, agent_id=aid, passed=True, fit_score=0.9),
            DispatchedEvent(session_id=SID, task_id=tid, agent_id=aid, reason="sole claimer"),
        ]
        evs += [ToolCalledEvent(session_id=SID, task_id=tid, agent_id=aid, tool_name=n, arguments={"i": i}, result="r", latency_ms=0.1) for i, n in enumerate(names)]
        evs += [
            ExecutedEvent(session_id=SID, task_id=tid, agent_id=aid, output_summary="s", output_content="c"),
            QAEvaluatedEvent(session_id=SID, task_id=tid, agent_id=aid, success=True, score=1.0, reason="r"),
        ]
        return evs

    def test_consecutive_same_tool_collapses(self):
        # grep, grep, read, grep -> 3 jalons tool
        graph = build_graph(self._run_with_tools(["grep", "grep", "read", "grep"]), _meta("t1", "x"))
        tool_steps = [s for s in graph.steps if s.milestone_type == "tool"]
        assert [s.detail.tool.tool_name for s in tool_steps] == ["grep", "read", "grep"]
        assert len(tool_steps[0].detail.tool.calls) == 2   # 2 grep fusionnés
        assert len(tool_steps[2].detail.tool.calls) == 1

    def test_tool_milestone_lights_agent_and_tool(self):
        graph = build_graph(self._run_with_tools(["grep"]), _meta("t1", "x"))
        ts = next(s for s in graph.steps if s.milestone_type == "tool")
        assert "ag" in ts.active_nodes and "tool:grep" in ts.active_nodes
        pairs = {(e.from_node, e.to) for e in ts.active_edges}
        assert ("dispatch", "ag") in pairs   # dispatch→agent reste allumé tant que k actif
        assert ("ag", "tool:grep") in pairs

    def test_tool_milestones_between_dispatch_and_agent(self):
        graph = build_graph(self._run_with_tools(["grep"]), _meta("t1", "x"))
        types = [s.milestone_type for s in graph.steps]
        assert types == ["input", "dispatch", "tool", "agent", "evaluator", "output"]


def _divided_meta(parent_id, desc):
    return SessionMeta(
        session_id=SID, started_at="2026-01-01T00:00:00Z", ended_at="2026-01-01T00:01:00Z",
        tasks=[SessionTaskRecord(id=parent_id, description=desc, winner_agent_id=None, outcome="divided", required_tags={})],
        agent_ids=["ag"],
    )


def _divided_events():
    """Parent divisé en 2 sous-tâches séquentielles, chacune dispatchée à ag, l'une avec un tool."""
    P, S1, S2 = "parent", "sub1", "sub2"
    return [
        TaskDividedEvent(session_id=SID, task_id=P, sub_tasks=[
            DividedSubTask(id=S1, description="investigate", depends_on=[]),
            DividedSubTask(id=S2, description="fix", depends_on=[S1]),
        ]),
        # sous-tâche 1 (avec tool)
        Phase1FilteredEvent(session_id=SID, task_id=S1, agent_id="ag", passed=True, fit_score=0.9),
        DispatchedEvent(session_id=SID, task_id=S1, agent_id="ag", reason="sole claimer"),
        ToolCalledEvent(session_id=SID, task_id=S1, agent_id="ag", tool_name="grep", arguments={}, result="r", latency_ms=0.1),
        ExecutedEvent(session_id=SID, task_id=S1, agent_id="ag", output_summary="s1", output_content="c1"),
        QAEvaluatedEvent(session_id=SID, task_id=S1, agent_id="ag", success=True, score=1.0, reason="r"),
        # sous-tâche 2 (sans tool)
        Phase1FilteredEvent(session_id=SID, task_id=S2, agent_id="ag", passed=True, fit_score=0.9),
        DispatchedEvent(session_id=SID, task_id=S2, agent_id="ag", reason="sole claimer"),
        ExecutedEvent(session_id=SID, task_id=S2, agent_id="ag", output_summary="s2", output_content="c2"),
        QAEvaluatedEvent(session_id=SID, task_id=S2, agent_id="ag", success=True, score=1.0, reason="r"),
        TaskAggregatedEvent(session_id=SID, task_id=P, sub_task_ids=[S1, S2], output_summary="final", output_content="final report"),
    ]


class TestDividedRunMilestones:
    def test_milestone_sequence(self):
        graph = build_graph(_divided_events(), _divided_meta("parent", "incident"))
        types = [s.milestone_type for s in graph.steps]
        assert types == [
            "input", "divider",
            "dispatch", "tool", "agent", "evaluator",   # sub1
            "dispatch", "agent", "evaluator",            # sub2 (pas de tool)
            "aggregator", "output",
        ]

    def test_divider_milestone_lists_sub_tasks(self):
        graph = build_graph(_divided_events(), _divided_meta("parent", "incident"))
        div = next(s for s in graph.steps if s.milestone_type == "divider")
        assert "divider" in div.active_nodes
        assert [st.id for st in div.detail.divider.sub_tasks] == ["sub1", "sub2"]
        pairs = {(e.from_node, e.to) for e in div.active_edges}
        assert ("input", "divider") in pairs

    def test_dispatch_backbone_divider_to_dispatch(self):
        graph = build_graph(_divided_events(), _divided_meta("parent", "incident"))
        first_disp = next(s for s in graph.steps if s.milestone_type == "dispatch")
        pairs = {(e.from_node, e.to) for e in first_disp.active_edges}
        assert ("divider", "dispatch") in pairs

    def test_subtask_detail_scoped(self):
        graph = build_graph(_divided_events(), _divided_meta("parent", "incident"))
        agent_steps = [s for s in graph.steps if s.milestone_type == "agent"]
        assert agent_steps[0].detail.agents["ag"].output_content == "c1"
        assert agent_steps[1].detail.agents["ag"].output_content == "c2"
        assert agent_steps[0].sub_task_id == "sub1"
        assert agent_steps[1].sub_task_id == "sub2"

    def test_aggregator_and_output(self):
        graph = build_graph(_divided_events(), _divided_meta("parent", "incident"))
        agg = next(s for s in graph.steps if s.milestone_type == "aggregator")
        assert agg.detail.aggregator.sub_task_ids == ["sub1", "sub2"]
        pairs = {(e.from_node, e.to) for e in agg.active_edges}
        assert ("evaluator", "aggregator") in pairs
        out = graph.steps[-1]
        assert out.milestone_type == "output"
        assert out.detail.output.output_content == "final report"
        out_pairs = {(e.from_node, e.to) for e in out.active_edges}
        assert ("aggregator", "output") in out_pairs


class TestTodoSimple:
    def test_root_only_and_done_at_output(self):
        graph = build_graph(_simple_run(), _meta("t1", "do it"))
        first = graph.steps[0].todo
        assert len(first) == 1 and first[0].is_root and first[0].state == "current"
        last = graph.steps[-1].todo
        assert last[0].state == "done"

    def test_root_failed_on_qa_fail(self):
        graph = build_graph(_simple_run(success=False), _meta("t1", "do it"))
        ev = next(s for s in graph.steps if s.milestone_type == "evaluator")
        assert ev.todo[0].state == "failed"


class TestTodoDivided:
    def test_subtasks_appear_at_divider(self):
        graph = build_graph(_divided_events(), _divided_meta("parent", "incident"))
        inp = graph.steps[0].todo
        assert len(inp) == 1 and inp[0].is_root
        div = next(s for s in graph.steps if s.milestone_type == "divider").todo
        assert {t.id for t in div if not t.is_root} == {"sub1", "sub2"}
        assert all(t.state == "pending" for t in div if not t.is_root)

    def test_subtask_current_then_done(self):
        graph = build_graph(_divided_events(), _divided_meta("parent", "incident"))
        # au dispatch de sub1, sub1 = current, sub2 = pending
        disp1 = next(s for s in graph.steps if s.milestone_type == "dispatch" and s.sub_task_id == "sub1")
        states = {t.id: t.state for t in disp1.todo if not t.is_root}
        assert states == {"sub1": "current", "sub2": "pending"}
        # à l'output, les deux sont done
        out = graph.steps[-1].todo
        done = {t.id: t.state for t in out if not t.is_root}
        assert done == {"sub1": "done", "sub2": "done"}


import pytest
from pathlib import Path
from aaosa.tracing.store import load_trace

_REAL = Path("runs/sessions/2026-06-02T09-24-21-12a72561")


@pytest.mark.skipif(not (_REAL / "trace.jsonl").exists(), reason="trace réelle gitignored absente")
class TestRealDividedTrace:
    def test_real_trace_milestone_shape(self):
        from aaosa.tracing.store import SessionMeta
        events = load_trace(_REAL / "trace.jsonl")
        meta = SessionMeta.model_validate_json((_REAL / "meta.json").read_text(encoding="utf-8"))
        graph = build_graph(events, meta)
        types = [s.milestone_type for s in graph.steps]
        assert types[0] == "input" and types[1] == "divider"
        assert types[-1] == "output" and types[-2] == "aggregator"
        assert types.count("evaluator") == 6     # 6 sous-tâches
        assert "tool" in types
        # tools RLE : moins de jalons tool que d'appels bruts (16 appels)
        n_tool_calls = sum(1 for e in events if e.type == "tool_called")
        assert sum(1 for t in types if t == "tool") < n_tool_calls


class TestFailAndUnassignedStates:
    def test_subtask_qa_fail_lights_testset_and_marks_todo(self):
        P, S1 = "p", "s1"
        events = [
            TaskDividedEvent(session_id=SID, task_id=P, sub_tasks=[DividedSubTask(id=S1, description="x", depends_on=[])]),
            Phase1FilteredEvent(session_id=SID, task_id=S1, agent_id="ag", passed=True, fit_score=0.9),
            DispatchedEvent(session_id=SID, task_id=S1, agent_id="ag", reason="sole claimer"),
            ExecutedEvent(session_id=SID, task_id=S1, agent_id="ag", output_summary="s", output_content="c"),
            QAEvaluatedEvent(session_id=SID, task_id=S1, agent_id="ag", success=False, score=0.0, reason="bad"),
            TaskAggregatedEvent(session_id=SID, task_id=P, sub_task_ids=[S1], output_summary="f", output_content="f"),
        ]
        graph = build_graph(events, _divided_meta("p", "x"))
        ev = next(s for s in graph.steps if s.milestone_type == "evaluator")
        assert ev.outcome == "qa_fail"
        assert "testset" in ev.active_nodes
        assert {(e.from_node, e.to) for e in ev.active_edges} >= {("evaluator", "testset")}
        sub_item = next(t for t in ev.todo if not t.is_root)
        assert sub_item.state == "failed"

    def test_subtask_unassigned_stops_at_dispatch(self):
        P, S1 = "p", "s1"
        events = [
            TaskDividedEvent(session_id=SID, task_id=P, sub_tasks=[DividedSubTask(id=S1, description="x", depends_on=[])]),
            Phase1FilteredEvent(session_id=SID, task_id=S1, agent_id="ag", passed=False, fit_score=0.0),
            UnassignedEvent(session_id=SID, task_id=S1, reason="no agent"),
            TaskAggregatedEvent(session_id=SID, task_id=P, sub_task_ids=[], output_summary="f", output_content="f"),
        ]
        graph = build_graph(events, _divided_meta("p", "x"))
        sub_types = [s.milestone_type for s in graph.steps if s.sub_task_id == S1]
        assert sub_types == ["dispatch"]   # pas d'agent/evaluator
        disp = next(s for s in graph.steps if s.milestone_type == "dispatch")
        assert disp.winner_agent_id is None
        assert disp.detail.dispatch.unassigned_reason == "no agent"
