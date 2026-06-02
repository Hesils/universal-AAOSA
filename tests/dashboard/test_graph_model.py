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
    DividerDetail,
    DividerSubTaskInfo,
    EvaluatorDetail,
    GraphEdge,
    GraphModel,
    GraphNode,
    GraphStep,
    StepDetail,
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
        assert edge.model_dump(by_alias=True) == {"from": "input", "to": "dispatch"}

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
