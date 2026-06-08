from datetime import datetime, timezone

from aaosa.qa.spec import CriterionSpec, EvaluatorSpec
from aaosa.schemas.output import LLMMetadata
from aaosa.tracing.events import (
    DispatchedEvent,
    DividedSubTask,
    EloUpdatedEvent,
    ExecutedEvent,
    Phase1FilteredEvent,
    Phase2ClaimedEvent,
    QAEvaluatedEvent,
    TagAcquiredEvent,
    TaskAggregatedEvent,
    TaskDividedEvent,
    ToolCalledEvent,
    UnassignedEvent,
)
from aaosa.tracing.store import SessionMeta, SessionTaskRecord
from dashboard.graph_model import (
    AggregatorDetail,
    DiagnosticDetail,
    DividerDetail,
    DividerSubTaskInfo,
    EvaluatorDetail,
    GraphEdge,
    GraphModel,
    GraphNode,
    GraphStep,
    RosterGapDetail,
    StepDetail,
    TaskBranch,
    ToolCallInfo,
    ToolDetail,
    TodoItem,
    build_graph,
)

SID = "sess-1"


def p1(tid, aid, passed=True, fit=0.8):
    return Phase1FilteredEvent(session_id=SID, task_id=tid, agent_id=aid, passed=passed, fit_score=fit)


def p2(tid, aid, decision="claim", just="mine"):
    return Phase2ClaimedEvent(session_id=SID, task_id=tid, agent_id=aid, decision=decision, justification=just)


def disp(tid, aid, reason="best fit"):
    return DispatchedEvent(session_id=SID, task_id=tid, agent_id=aid, reason=reason)


def ex(tid, aid, summary="out", content="full output", meta=None):
    return ExecutedEvent(session_id=SID, task_id=tid, agent_id=aid, output_summary=summary, output_content=content, llm_metadata=meta)


def unassigned(tid, reason="no agent"):
    return UnassignedEvent(session_id=SID, task_id=tid, reason=reason)


def qa(tid, aid, success=True, score=1.0, reason="ok", criteria=None, judge=None, spec=None):
    return QAEvaluatedEvent(session_id=SID, task_id=tid, agent_id=aid, success=success, score=score, reason=reason, criteria_results=criteria or {}, judge=judge, spec=spec)


def elo(tid, aid, deltas):
    return EloUpdatedEvent(session_id=SID, task_id=tid, agent_id=aid, deltas=deltas)


def tag(tid, aid, t, initial):
    return TagAcquiredEvent(session_id=SID, task_id=tid, agent_id=aid, tag=t, initial_elo=initial)


def tool(tid, aid, name, args=None, result="r", latency=0.5):
    return ToolCalledEvent(session_id=SID, task_id=tid, agent_id=aid, tool_name=name, arguments=args or {}, result=result, latency_ms=latency)


class TestGraphEdgeAlias:
    def test_from_alias_in_json(self):
        edge = GraphEdge(from_node="input", to="dispatch")
        assert edge.model_dump(by_alias=True) == {"from": "input", "to": "dispatch", "flow": "ascent"}

    def test_construct_by_field_name(self):
        edge = GraphEdge(from_node="a", to="b")
        assert edge.from_node == "a" and edge.to == "b"


class TestNewDetailTypes:
    def test_divider_detail(self):
        d = DividerDetail(divided=True, sub_tasks=[DividerSubTaskInfo(id="s1", description="x", depends_on=[])])
        assert d.divided is True and d.sub_tasks[0].id == "s1"

    def test_aggregator_detail(self):
        d = AggregatorDetail(aggregated=True, sub_task_ids=["s1"], output_summary="s", output_content="c")
        assert d.sub_task_ids == ["s1"]

    def test_tool_detail_groups_calls(self):
        d = ToolDetail(agent_id="ag", tool_name="grep", calls=[ToolCallInfo(tool_name="grep", arguments={"p": "x"}, result="r", latency_ms=0.1)])
        assert d.tool_name == "grep" and len(d.calls) == 1

    def test_evaluator_detail_carries_spec(self):
        spec = EvaluatorSpec(criteria=[CriterionSpec(name="non_empty", gate=True)])
        d = EvaluatorDetail(ran=True, success=True, score=1.0, reason="ok", criteria_results={"non_empty": True}, judge=None, spec=spec)
        assert d.spec.criteria[0].name == "non_empty"

    def test_todo_item(self):
        t = TodoItem(id="s1", description="x", state="current", is_root=False)
        assert t.state == "current" and t.is_root is False


class TestGraphStepIsMilestone:
    def test_step_has_milestone_fields(self):
        node = GraphNode(id="input", layer="top", type="input", label="Input")
        step = GraphStep(
            milestone_type="input", label="INPUT", sub_task_id=None, order_index=None,
            active_nodes=["input"], active_edges=[], winner_agent_id=None, outcome="no_qa",
            detail=StepDetail.empty(task_id="t1", description="d"), todo=[],
        )
        model = GraphModel(nodes=[node], edges=[], steps=[step])
        assert model.steps[0].milestone_type == "input"
        assert model.steps[0].active_nodes == ["input"]


class TestSerieDModelExtensions:
    def test_edge_flow(self):
        e = GraphEdge(from_node="a", to="b", flow="descent")
        assert e.flow == "descent"
        assert GraphEdge(from_node="a", to="b").flow == "ascent"   # défaut documenté

    def test_edge_flow_serialized(self):
        e = GraphEdge(from_node="a", to="b", flow="transient")
        assert e.model_dump(by_alias=True) == {"from": "a", "to": "b", "flow": "transient"}

    def test_node_carries_task_and_agent(self):
        n = GraphNode(id="agent:t1:ag", layer="bottom", type="agent", label="ag",
                      task_id="t1", agent_id="ag")
        assert n.task_id == "t1" and n.agent_id == "ag"
        assert GraphNode(id="input", layer="top", type="input", label="Input").task_id is None

    def test_step_pass_index_default(self):
        step = GraphStep(milestone_type="dispatch", label="DISPATCH",
                         detail=StepDetail.empty(task_id="t", description="d"))
        assert step.pass_index == 0

    def test_diagnostic_detail(self):
        d = DiagnosticDetail(attribution="evaluator", reason="strict", consignes="relax",
                             route_taken="evaluator")
        assert d.route_taken == "evaluator"

    def test_roster_gap_detail(self):
        d = RosterGapDetail(missing_tags=["legal", "gdpr"])
        assert d.missing_tags == ["legal", "gdpr"]

    def test_step_detail_new_fields_default_none(self):
        d = StepDetail.empty(task_id="t", description="x")
        assert d.diagnostic is None and d.roster_gap is None

    def test_todo_item_hierarchy(self):
        t = TodoItem(id="s1", description="x", state="current", is_root=False,
                     parent_id="root", depth=1, first_step_index=4, note="pass 2")
        assert t.parent_id == "root" and t.depth == 1 and t.first_step_index == 4
        bare = TodoItem(id="r", description="x", state="done", is_root=True)
        assert bare.parent_id is None and bare.depth == 0 and bare.first_step_index is None

    def test_task_branch(self):
        b = TaskBranch(id="s1", parent_id="root", depth=1, order_index=0, description="sub")
        assert b.depth == 1

    def test_new_outcomes_and_types_accepted(self):
        step = GraphStep(milestone_type="diagnostic", label="DIAGNOSTIC", outcome="diagnosed",
                         detail=StepDetail.empty(task_id="t", description="d"))
        assert step.outcome == "diagnosed"
        n = GraphNode(id="roster_gap:t1", layer="center", type="roster_gap", label="GAP", task_id="t1")
        assert n.type == "roster_gap"


# ---------------------------------------------------------------------------
# Live-mode tolerance tests: build_graph on partial / growing traces
# ---------------------------------------------------------------------------

def _provisional_meta_live(task_id: str) -> SessionMeta:
    now = datetime(2026, 6, 8, 11, 0, 0, tzinfo=timezone.utc)
    return SessionMeta(
        session_id="live", started_at=now, ended_at=now, status="running",
        tasks=[SessionTaskRecord(id=task_id, description="root incident",
                                 winner_agent_id=None, outcome="divided",
                                 required_tags={"security": 50})],
        agent_ids=["a1"],
    )


def test_build_graph_input_only_no_events():
    # trace vide + meta provisoire -> graphe INPUT-seul, pas de crash
    g = build_graph([], _provisional_meta_live("root"))
    assert g.steps[0].milestone_type == "input"
    assert g.steps[0].detail.input.description == "root incident"


def test_build_graph_partial_trace_phase1_only():
    # début de run : phase1 émise, rien d'autre -> graphe valide croissant
    meta = _provisional_meta_live("root")
    events = [
        Phase1FilteredEvent(session_id="live", task_id="root", agent_id="a1", passed=True, fit_score=0.8),
    ]
    g = build_graph(events, meta)
    assert g.steps[0].milestone_type == "input"
    assert len(g.steps) >= 1  # pas de crash, graphe partiel rendu


def test_build_graph_growing_trace_adds_steps():
    # un event supplémentaire produit au moins autant d'étapes (graphe cumulatif)
    meta = _provisional_meta_live("root")
    base = [Phase1FilteredEvent(session_id="live", task_id="root", agent_id="a1", passed=True, fit_score=0.8)]
    grown = base + [DispatchedEvent(session_id="live", task_id="root", agent_id="a1", reason="best fit")]
    assert len(build_graph(grown, meta).steps) >= len(build_graph(base, meta).steps)
