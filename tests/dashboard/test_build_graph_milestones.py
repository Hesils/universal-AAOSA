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
from dashboard.graph_model import build_graph

SID = "s"

# NOTE: TestNodes and TestEdges (which called deleted helpers _build_nodes, _build_edges,
# _tool_node_id) have been deleted. That machinery is now tested via build_graph() in
# tests/dashboard/test_build_graph_tree.py::TestStructure.


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
    def test_milestone_sequence_no_tags(self):
        # no required_tags → no tagger
        graph = build_graph(_simple_run(), _meta("t1", "do it"))
        assert [s.milestone_type for s in graph.steps] == ["input", "dispatch", "agent", "evaluator", "output"]

    def test_milestone_sequence_with_tags(self):
        # required_tags present → tagger inserted
        graph = build_graph(_simple_run(), _meta("t1", "do it", {"backend": 70}))
        assert [s.milestone_type for s in graph.steps] == ["input", "tagger", "dispatch", "agent", "evaluator", "output"]

    def test_input_milestone_synthesized_from_meta(self):
        graph = build_graph(_simple_run(), _meta("t1", "do it", {"backend": 70}))
        inp = graph.steps[0]
        assert inp.active_nodes == ["input"]
        assert inp.detail.input.description == "do it"
        assert inp.detail.input.required_tags == {"backend": 70}

    def test_dispatch_milestone_lights_input_dispatch_and_winner(self):
        # No required_tags → backbone goes input → dispatch:t1
        graph = build_graph(_simple_run(), _meta("t1", "do it"))
        disp_step = next(s for s in graph.steps if s.milestone_type == "dispatch")
        assert "dispatch:t1" in disp_step.active_nodes and "agent:t1:ag" in disp_step.active_nodes
        pairs = {(e.from_node, e.to) for e in disp_step.active_edges}
        assert ("input", "dispatch:t1") in pairs   # backbone (no tagger)
        assert ("dispatch:t1", "agent:t1:ag") in pairs  # fan-out
        assert disp_step.winner_agent_id == "ag"

    def test_agent_milestone_carries_output(self):
        graph = build_graph(_simple_run(), _meta("t1", "do it"))
        agent_step = next(s for s in graph.steps if s.milestone_type == "agent")
        assert agent_step.active_nodes == ["agent:t1:ag"]
        assert agent_step.detail.agents["ag"].output_content == "content"

    def test_evaluator_milestone_pass(self):
        graph = build_graph(_simple_run(success=True), _meta("t1", "do it"))
        ev = next(s for s in graph.steps if s.milestone_type == "evaluator")
        assert ev.outcome == "qa_pass"
        assert "evaluator:t1" in ev.active_nodes
        pairs = {(e.from_node, e.to) for e in ev.active_edges}
        assert ("agent:t1:ag", "evaluator:t1") in pairs

    def test_output_milestone_backbone_persists(self):
        graph = build_graph(_simple_run(), _meta("t1", "do it"))
        out = graph.steps[-1]
        assert out.milestone_type == "output"
        assert "output" in out.active_nodes
        pairs = {(e.from_node, e.to) for e in out.active_edges}
        assert ("input", "dispatch:t1") in pairs   # backbone cumulatif toujours présent
        assert ("evaluator:t1", "output") in pairs
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
        assert "agent:t1:ag" in ts.active_nodes and "tool:t1:grep" in ts.active_nodes
        pairs = {(e.from_node, e.to) for e in ts.active_edges}
        assert ("dispatch:t1", "agent:t1:ag") in pairs   # dispatch→agent reste allumé tant que actif
        assert ("agent:t1:ag", "tool:t1:grep") in pairs

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
            DividedSubTask(id=S1, description="investigate", depends_on=[], required_tags={"backend": 70}),
            DividedSubTask(id=S2, description="fix", depends_on=[], required_tags={"python": 60}),
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
        assert "divider:parent" in div.active_nodes
        assert [st.id for st in div.detail.divider.sub_tasks] == ["sub1", "sub2"]
        pairs = {(e.from_node, e.to) for e in div.active_edges}
        assert ("input", "divider:parent") in pairs

    def test_dispatch_backbone_divider_to_dispatch(self):
        graph = build_graph(_divided_events(), _divided_meta("parent", "incident"))
        first_disp = next(s for s in graph.steps if s.milestone_type == "dispatch")
        pairs = {(e.from_node, e.to) for e in first_disp.active_edges}
        assert ("divider:parent", "dispatch:sub1") in pairs

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
        assert ("evaluator:sub2", "aggregator:parent") in pairs

    def test_evaluator_pass_lights_aggregator_progressively(self):
        # Récit progressif : chaque evaluator qa_pass allume l'aggregator + arête transitoire,
        # et le compteur collected s'incrémente (1, puis 2).
        graph = build_graph(_divided_events(), _divided_meta("parent", "incident"))
        ev_steps = [s for s in graph.steps if s.milestone_type == "evaluator"]
        assert len(ev_steps) == 2
        for k, ev in enumerate(ev_steps, start=1):
            assert "aggregator:parent" in ev.active_nodes
            assert ("evaluator:" + ev.sub_task_id, "aggregator:parent") in {(e.from_node, e.to) for e in ev.active_edges}
            assert ev.detail.aggregator.aggregated is False
            assert ev.detail.aggregator.collected == k
            assert ev.detail.aggregator.total == 2

    def test_subtask_required_tags_propagated(self):
        graph = build_graph(_divided_events(), _divided_meta("parent", "incident"))
        div = next(s for s in graph.steps if s.milestone_type == "divider")
        tags_by_id = {st.id: st.required_tags for st in div.detail.divider.sub_tasks}
        assert tags_by_id == {"sub1": {"backend": 70}, "sub2": {"python": 60}}
        # le modal Input d'une sous-tâche montre SES tags (pas ceux du parent)
        disp1 = next(s for s in graph.steps if s.milestone_type == "dispatch" and s.sub_task_id == "sub1")
        assert disp1.detail.input.required_tags == {"backend": 70}
        out = graph.steps[-1]
        assert out.milestone_type == "output"
        assert out.detail.output.output_content == "final report"
        out_pairs = {(e.from_node, e.to) for e in out.active_edges}
        assert ("aggregator:parent", "output") in out_pairs
        # état terminal : l'arête aggregator→output est dans le backbone cumulatif de l'output
        # (active_nodes au jalon OUTPUT contient uniquement ["output"] dans le nouveau modèle)
        assert "output" in out.active_nodes
        assert "aggregator:parent" not in out.active_nodes


class TestTodoSimple:
    def test_root_only_and_done_at_output(self):
        graph = build_graph(_simple_run(), _meta("t1", "do it"))
        first = graph.steps[0].todo
        assert len(first) == 1 and first[0].is_root and first[0].state == "current"
        last = graph.steps[-1].todo
        assert last[0].state == "done"

    def test_root_failed_on_qa_fail(self):
        # qa_fail without DiagnosedEvent: walk ends at evaluator (no output milestone)
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
        # Invariants assouplis : types précis dépendent de la trace réelle
        assert types[0] == "input"
        assert "divider" in types
        assert types[-1] == "output"
        # tools RLE : moins de jalons tool que d'appels bruts (16 appels)
        n_tool_calls = sum(1 for e in events if e.type == "tool_called")
        assert sum(1 for t in types if t == "tool") < n_tool_calls
        assert "tool" in types


class TestFailAndUnassignedStates:
    def test_subtask_qa_fail_marks_todo_failed(self):
        # testset node is REMOVED from the graph (serie D); detail.testset still present
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
        # testset node no longer in graph (serie D removed it) — but detail still carries the fork flag
        assert "testset" not in {n.id for n in graph.nodes}
        assert ev.detail.testset.forked is True
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
