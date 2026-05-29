from aaosa.schemas.output import LLMMetadata
from aaosa.qa.judge import JudgeBreakdown, DimensionScore
from aaosa.tracing.events import (
    DispatchedEvent,
    EloUpdatedEvent,
    ExecutedEvent,
    Phase1FilteredEvent,
    Phase2ClaimedEvent,
    QAEvaluatedEvent,
    TagAcquiredEvent,
    UnassignedEvent,
)
from dashboard.graph_model import (
    AgentDetail,
    CandidateInfo,
    ClaimInfo,
    DispatchDetail,
    EvaluatorDetail,
    GraphEdge,
    GraphModel,
    GraphNode,
    GraphStep,
    InputDetail,
    OutputDetail,
    StepDetail,
    TagAcquiredInfo,
    TestSetDetail,
    _segment_runs,
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


def qa(tid, aid, success=True, score=1.0, reason="ok", criteria=None, judge=None):
    return QAEvaluatedEvent(session_id=SID, task_id=tid, agent_id=aid, success=success, score=score, reason=reason, criteria_results=criteria or {}, judge=judge)


def elo(tid, aid, deltas):
    return EloUpdatedEvent(session_id=SID, task_id=tid, agent_id=aid, deltas=deltas)


def tag(tid, aid, t, initial):
    return TagAcquiredEvent(session_id=SID, task_id=tid, agent_id=aid, tag=t, initial_elo=initial)


class TestGraphEdgeAlias:
    def test_from_alias_in_json(self):
        edge = GraphEdge(from_node="input", to="dispatch")
        dumped = edge.model_dump(by_alias=True)
        assert dumped == {"from": "input", "to": "dispatch"}

    def test_construct_by_field_name(self):
        edge = GraphEdge(from_node="a", to="b")
        assert edge.from_node == "a"
        assert edge.to == "b"


class TestGraphModelConstruction:
    def test_minimal_model(self):
        node = GraphNode(id="input", layer="top", type="input", label="Input")
        model = GraphModel(nodes=[node], edges=[], steps=[])
        assert model.nodes[0].id == "input"
        assert model.nodes[0].layer == "top"

    def test_step_detail_shape(self):
        detail = StepDetail(
            input=InputDetail(task_id="t1", description="d", required_tags={}),
            dispatch=DispatchDetail(
                candidates=[], claims=[], winner_agent_id=None,
                dispatch_reason=None, unassigned_reason=None,
            ),
            agents={},
            evaluator=EvaluatorDetail(
                ran=False, success=None, score=None, reason=None,
                criteria_results={}, judge=None,
            ),
            output=OutputDetail(
                produced=False, output_summary=None,
                output_content=None, llm_metadata=None,
            ),
            testset=TestSetDetail(forked=False, from_task_id="t1"),
        )
        step = GraphStep(
            task_id="t1", label="d", active_nodes=["input"],
            active_edges=[], winner_agent_id=None, outcome="unassigned",
            detail=detail,
        )
        assert step.outcome == "unassigned"
        assert step.detail.input.task_id == "t1"


class TestSegmentRuns:
    def test_single_run_returns_all(self):
        run = [p1("t1", "a"), p2("t1", "a"), disp("t1", "a"), ex("t1", "a"), qa("t1", "a")]
        assert _segment_runs(run) == run

    def test_session_run_keeps_trailing_elo(self):
        run = [p1("t1", "a"), disp("t1", "a"), ex("t1", "a"), qa("t1", "a"),
               elo("t1", "a", {"python": 5}), tag("t1", "a", "css", 50)]
        assert _segment_runs(run) == run

    def test_two_runs_keeps_last(self):
        run1 = [p1("t1", "a"), p1("t1", "b"), disp("t1", "a"), ex("t1", "a"), qa("t1", "a", success=False)]
        run2 = [p1("t1", "a"), p1("t1", "b"), disp("t1", "b"), ex("t1", "b"), qa("t1", "b", success=True)]
        last = _segment_runs(run1 + run2)
        assert last == run2

    def test_three_runs_keeps_last(self):
        def mk(winner):
            return [p1("t1", "a"), p1("t1", "b"), disp("t1", winner), ex("t1", winner), qa("t1", winner)]
        run_a = mk("a")
        run_b = mk("b")
        run_a_again = mk("a")
        runs = run_a + run_b + run_a_again
        last = _segment_runs(runs)
        assert last == run_a_again

    def test_unassigned_run_segments(self):
        run1 = [p1("t1", "a"), unassigned("t1")]
        run2 = [p1("t1", "a"), disp("t1", "a"), ex("t1", "a"), qa("t1", "a")]
        assert _segment_runs(run1 + run2) == run2


def _single_pass_run(tid="t1", winner="a", others=("b",)):
    events = [p1(tid, winner, True, 0.9)]
    for o in others:
        events.append(p1(tid, o, True, 0.4))
    events.append(p2(tid, winner, "claim", "mine"))
    events += [disp(tid, winner), ex(tid, winner), qa(tid, winner, success=True),
               elo(tid, winner, {"python": 5})]
    return events


class TestBuildNodesEdges:
    def test_fixed_nodes_present(self):
        model = build_graph(_single_pass_run())
        by_id = {n.id: n for n in model.nodes}
        assert by_id["input"].layer == "top"
        assert by_id["dispatch"].layer == "center"
        assert by_id["evaluator"].layer == "center"
        assert by_id["output"].layer == "top"
        assert by_id["testset"].layer == "top"

    def test_agent_nodes_bottom(self):
        model = build_graph(_single_pass_run(winner="a", others=("b",)))
        agents = [n for n in model.nodes if n.type == "agent"]
        assert {n.id for n in agents} == {"a", "b"}
        assert all(n.layer == "bottom" for n in agents)
        assert all(n.label == n.id for n in agents)  # label = agent_id (D3)

    def test_static_edges(self):
        model = build_graph(_single_pass_run(winner="a", others=("b",)))
        pairs = {(e.from_node, e.to) for e in model.edges}
        assert ("input", "dispatch") in pairs
        assert ("dispatch", "a") in pairs and ("dispatch", "b") in pairs
        assert ("a", "evaluator") in pairs and ("b", "evaluator") in pairs
        assert ("a", "output") in pairs and ("b", "output") in pairs
        assert ("evaluator", "output") in pairs
        assert ("evaluator", "testset") in pairs
