from datetime import datetime, timedelta, timezone

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
from aaosa.tracing.store import SessionMeta, SessionTaskRecord
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


def _meta(records):
    now = datetime.now(timezone.utc)
    return SessionMeta(
        session_id=SID, started_at=now, ended_at=now,
        tasks=records, agent_ids=["a", "b"],
    )


class TestBuildStepPass:
    def test_one_step_pass(self):
        meta = LLMMetadata(model_name="gpt-4o-mini", tokens_in=10, tokens_out=5, latency_ms=42.0)
        events = [
            p1("t1", "a", True, 0.9), p1("t1", "b", False, 0.2),
            p2("t1", "a", "claim", "css is mine"),
            disp("t1", "a", "highest fit"),
            ex("t1", "a", summary="fixed it", content="the full fix", meta=meta),
            qa("t1", "a", success=True, score=0.85, reason="good", criteria={"non_empty": True}),
            elo("t1", "a", {"css": 5}),
            tag("t1", "a", "hover", 50),
        ]
        sm = _meta([SessionTaskRecord(
            id="t1", description="Fix CSS hover", winner_agent_id="a",
            outcome="qa_pass", required_tags={"css": 60},
        )])
        model = build_graph(events, sm)

        assert len(model.steps) == 1
        step = model.steps[0]
        assert step.task_id == "t1"
        assert step.label == "Fix CSS hover"
        assert step.winner_agent_id == "a"
        assert step.outcome == "qa_pass"
        assert step.active_nodes == ["input", "dispatch", "a", "evaluator", "output"]
        active_pairs = [(e.from_node, e.to) for e in step.active_edges]
        assert active_pairs == [("input", "dispatch"), ("dispatch", "a"), ("a", "evaluator"), ("evaluator", "output")]

    def test_step_detail_pass(self):
        meta = LLMMetadata(model_name="gpt-4o-mini", tokens_in=10, tokens_out=5, latency_ms=42.0)
        events = [
            p1("t1", "a", True, 0.9), p1("t1", "b", False, 0.2),
            p2("t1", "a", "claim", "css is mine"),
            disp("t1", "a", "highest fit"),
            ex("t1", "a", summary="fixed", content="the full fix", meta=meta),
            qa("t1", "a", success=True, score=0.85, reason="good", criteria={"non_empty": True}),
            elo("t1", "a", {"css": 5}),
            tag("t1", "a", "hover", 50),
        ]
        sm = _meta([SessionTaskRecord(
            id="t1", description="Fix CSS hover", winner_agent_id="a",
            outcome="qa_pass", required_tags={"css": 60},
        )])
        d = build_graph(events, sm).steps[0].detail

        assert d.input.required_tags == {"css": 60}
        assert d.input.description == "Fix CSS hover"
        assert {c.agent_id for c in d.dispatch.candidates} == {"a", "b"}
        assert d.dispatch.winner_agent_id == "a"
        assert d.dispatch.dispatch_reason == "highest fit"
        assert len(d.dispatch.claims) == 1 and d.dispatch.claims[0].agent_id == "a"

        wa = d.agents["a"]
        assert wa.role == "winner"
        assert wa.fit_score == 0.9
        assert wa.claim_decision == "claim"
        assert wa.output_content == "the full fix"
        assert wa.llm_metadata.tokens_in == 10
        assert wa.elo_deltas == {"css": 5}
        assert wa.tags_acquired[0].tag == "hover"

        ca = d.agents["b"]
        assert ca.role == "candidate"
        assert ca.passed is False
        assert ca.output_content is None
        assert ca.elo_deltas == {}

        assert d.evaluator.ran is True
        assert d.evaluator.success is True
        assert d.evaluator.criteria_results == {"non_empty": True}
        assert d.output.produced is True
        assert d.output.output_content == "the full fix"
        assert d.testset.forked is False


class TestBuildStepVariants:
    def test_unassigned(self):
        events = [p1("t1", "a", False, 0.1), p1("t1", "b", False, 0.1), unassigned("t1", "no candidate claimed")]
        step = build_graph(events).steps[0]
        assert step.outcome == "unassigned"
        assert step.winner_agent_id is None
        assert step.active_nodes == ["input", "dispatch"]
        assert [(e.from_node, e.to) for e in step.active_edges] == [("input", "dispatch")]
        assert step.detail.dispatch.unassigned_reason == "no candidate claimed"
        assert step.detail.evaluator.ran is False
        assert step.detail.output.produced is False

    def test_no_qa(self):
        events = [p1("t1", "a", True, 0.9), p2("t1", "a", "claim", "mine"),
                  disp("t1", "a"), ex("t1", "a", content="done")]
        step = build_graph(events).steps[0]
        assert step.outcome == "no_qa"
        assert step.winner_agent_id == "a"
        assert step.active_nodes == ["input", "dispatch", "a", "output"]
        assert [(e.from_node, e.to) for e in step.active_edges] == [("input", "dispatch"), ("dispatch", "a"), ("a", "output")]
        assert step.detail.evaluator.ran is False
        assert step.detail.output.produced is True

    def test_qa_fail_forks_to_testset(self):
        events = [p1("t1", "a", True, 0.9), p2("t1", "a", "claim", "mine"),
                  disp("t1", "a"), ex("t1", "a", content="weak"),
                  qa("t1", "a", success=False, score=0.3, reason="too short", criteria={"min_length": False})]
        step = build_graph(events).steps[0]
        assert step.outcome == "qa_fail"
        assert step.winner_agent_id == "a"
        assert step.active_nodes == ["input", "dispatch", "a", "evaluator", "testset"]
        assert [(e.from_node, e.to) for e in step.active_edges] == [("input", "dispatch"), ("dispatch", "a"), ("a", "evaluator"), ("evaluator", "testset")]
        assert step.detail.testset.forked is True
        assert step.detail.testset.from_task_id == "t1"
        assert step.detail.evaluator.success is False
        assert step.detail.output.produced is True  # output produit puis rejeté


class TestInputDetailContext:
    def test_input_detail_carries_context(self):
        events = [p1("t1", "a", True, 0.9), disp("t1", "a", "fit"), ex("t1", "a", summary="s", content="c")]
        sm = _meta([SessionTaskRecord(
            id="t1", description="Fix CSS", winner_agent_id="a",
            outcome="no_qa", required_tags={"css": 60}, context="Fichier source: style.css ...",
        )])
        d = build_graph(events, sm).steps[0].detail
        assert d.input.context == "Fichier source: style.css ..."

    def test_input_detail_context_none_when_absent(self):
        events = [p1("t1", "a", True, 0.9), disp("t1", "a", "fit"), ex("t1", "a", summary="s", content="c")]
        sm = _meta([SessionTaskRecord(
            id="t1", description="Fix CSS", winner_agent_id="a",
            outcome="no_qa", required_tags={"css": 60},
        )])
        d = build_graph(events, sm).steps[0].detail
        assert d.input.context is None


class TestMultiTask:
    def test_steps_ordered_by_meta(self):
        events = (
            _single_pass_run(tid="t2", winner="a", others=("b",))
            + _single_pass_run(tid="t1", winner="b", others=("a",))
        )
        sm = _meta([
            SessionTaskRecord(id="t1", description="first", winner_agent_id="b", outcome="qa_pass", required_tags={"x": 1}),
            SessionTaskRecord(id="t2", description="second", winner_agent_id="a", outcome="qa_pass", required_tags={"y": 1}),
        ])
        steps = build_graph(events, sm).steps
        assert [s.task_id for s in steps] == ["t1", "t2"]
        assert [s.label for s in steps] == ["first", "second"]

    def test_steps_ordered_by_timestamp_when_no_meta(self):
        base = datetime(2026, 5, 29, 10, 0, 0, tzinfo=timezone.utc)
        e_early = p1("t1", "a", True, 0.9)
        e_early.timestamp = base
        e_late = p1("t2", "a", True, 0.9)
        e_late.timestamp = base + timedelta(seconds=10)
        # t2 appears before t1 in the list, but t1 is earlier
        steps = build_graph([e_late, e_early]).steps
        assert [s.task_id for s in steps] == ["t1", "t2"]

    def test_meta_label_fallback_to_task_id_when_no_meta(self):
        step = build_graph(_single_pass_run(tid="abc", winner="a", others=())).steps[0]
        assert step.label == "abc"
        assert step.detail.input.required_tags == {}

    def test_multi_claim_winner_from_dispatch(self):
        events = [
            p1("t1", "a", True, 0.8), p1("t1", "b", True, 0.7),
            p2("t1", "a", "claim", "a wants it"),
            p2("t1", "b", "claim", "b wants it"),
            disp("t1", "b", "b had higher score"),
            ex("t1", "b", content="b output"),
            qa("t1", "b", success=True),
        ]
        step = build_graph(events).steps[0]
        assert step.winner_agent_id == "b"
        assert len(step.detail.dispatch.claims) == 2
        assert step.detail.agents["a"].role == "candidate"
        assert step.detail.agents["b"].role == "winner"


class TestHealthCheckMode:
    def test_n_runs_keeps_last_run(self):
        # 3 runs of the same case, no meta, no ELO (V1 mode)
        def run(winner, success):
            return [p1("c1", "a", True, 0.8), p1("c1", "b", True, 0.6),
                    p2("c1", winner, "claim", "mine"),
                    disp("c1", winner), ex("c1", winner, content=f"{winner} out"),
                    qa("c1", winner, success=success)]
        events = run("a", False) + run("a", True) + run("b", True)
        model = build_graph(events)
        assert len(model.steps) == 1
        step = model.steps[0]
        assert step.winner_agent_id == "b"      # last run
        assert step.outcome == "qa_pass"
        assert step.detail.agents["b"].output_content == "b out"
        assert step.detail.agents["b"].elo_deltas == {}  # no ELO in health check

    def test_health_check_unassigned_last_run(self):
        def ok_run():
            return [p1("c1", "a", True, 0.8), p2("c1", "a", "claim", "mine"),
                    disp("c1", "a"), ex("c1", "a", content="out"), qa("c1", "a", success=True)]
        def fail_run():
            return [p1("c1", "a", False, 0.1), unassigned("c1", "nobody claimed")]
        events = ok_run() + fail_run()
        step = build_graph(events).steps[0]
        assert step.outcome == "unassigned"
        assert step.winner_agent_id is None

    def test_label_is_task_id_without_meta(self):
        events = [p1("c1", "a", True, 0.9), p2("c1", "a", "claim", "x"),
                  disp("c1", "a"), ex("c1", "a", content="o"), qa("c1", "a", success=True)]
        step = build_graph(events).steps[0]
        assert step.label == "c1"
