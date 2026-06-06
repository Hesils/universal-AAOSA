from aaosa.qa.spec import CriterionSpec, EvaluatorSpec
from aaosa.tracing.events import (
    DiagnosedEvent,
    DispatchedEvent,
    DividedSubTask,
    ExecutedEvent,
    Phase1FilteredEvent,
    Phase2ClaimedEvent,
    QAEvaluatedEvent,
    RosterGapEvent,
    TaskAggregatedEvent,
    TaskDividedEvent,
    ToolCalledEvent,
    UnassignedEvent,
)
from aaosa.tracing.store import SessionMeta, SessionTaskRecord
from dashboard.graph_model import _build_tree, _parse_runs, build_graph

SID = "s"


def p1(tid, aid, passed=True, fit=0.9):
    return Phase1FilteredEvent(session_id=SID, task_id=tid, agent_id=aid, passed=passed, fit_score=fit)


def p2(tid, aid, decision="claim"):
    return Phase2ClaimedEvent(session_id=SID, task_id=tid, agent_id=aid, decision=decision, justification="mine")


def disp(tid, aid):
    return DispatchedEvent(session_id=SID, task_id=tid, agent_id=aid, reason="sole claimer")


def ex(tid, aid, content="content"):
    return ExecutedEvent(session_id=SID, task_id=tid, agent_id=aid, output_summary=content[:20], output_content=content)


def qa(tid, aid, success=True, score=None, spec=None):
    return QAEvaluatedEvent(session_id=SID, task_id=tid, agent_id=aid, success=success,
                            score=score if score is not None else (1.0 if success else 0.2),
                            reason="ok" if success else "bad", spec=spec)


def diag(tid, aid, attribution, reason="r", consignes=None):
    return DiagnosedEvent(session_id=SID, task_id=tid, agent_id=aid,
                          attribution=attribution, reason=reason, consignes=consignes)


def tool(tid, aid, name):
    return ToolCalledEvent(session_id=SID, task_id=tid, agent_id=aid, tool_name=name,
                           arguments={}, result="r", latency_ms=0.1)


def divided(parent, subs):
    """subs = [(id, description, depends_on, required_tags)]"""
    return TaskDividedEvent(session_id=SID, task_id=parent, sub_tasks=[
        DividedSubTask(id=i, description=d, depends_on=deps, required_tags=tags)
        for (i, d, deps, tags) in subs
    ])


def aggregated(parent, sub_ids, content="final"):
    return TaskAggregatedEvent(session_id=SID, task_id=parent, sub_task_ids=sub_ids,
                               output_summary=content, output_content=content)


def meta(task_id, desc, tags=None):
    return SessionMeta(
        session_id=SID, started_at="2026-01-01T00:00:00Z", ended_at="2026-01-01T00:01:00Z",
        tasks=[SessionTaskRecord(id=task_id, description=desc, winner_agent_id=None,
                                 outcome="qa_pass",
                                 required_tags={"python": 50} if tags is None else tags)],
        agent_ids=["ag"],
    )


def simple_pass(tid, aid="ag", success=True, with_tool=None, content="content"):
    evs = [p1(tid, aid), p2(tid, aid), disp(tid, aid)]
    if with_tool:
        evs.append(tool(tid, aid, with_tool))
    evs += [ex(tid, aid, content), qa(tid, aid, success=success)]
    return evs


class TestParseRuns:
    def test_partition_by_task_id(self):
        events = simple_pass("t1") + simple_pass("t2", content="other")
        runs = _parse_runs(events)
        assert set(runs) == {"t1", "t2"}
        assert runs["t1"].passes[0].executed.output_content == "content"
        assert runs["t2"].passes[0].executed.output_content == "other"

    def test_single_pass_no_diag(self):
        runs = _parse_runs(simple_pass("t1"))
        r = runs["t1"]
        assert len(r.passes) == 1
        assert r.diagnosed is None and r.reeval is None
        assert r.passes[0].winner_id == "ag"
        assert r.succeeded is True

    def test_retry_pass_after_diagnosed(self):
        # pass 0 (fail) → diagnosed agent → pass 1 (success)
        events = (simple_pass("t1", success=False)
                  + [diag("t1", "ag", "agent", consignes="be precise")]
                  + simple_pass("t1", success=True, content="fixed"))
        r = _parse_runs(events)["t1"]
        assert len(r.passes) == 2
        assert r.passes[0].outcome == "qa_fail"
        assert r.passes[1].outcome == "qa_pass"
        assert r.diagnosed.attribution == "agent"
        assert r.reeval is None
        assert r.succeeded is True

    def test_reeval_captured_separately(self):
        # route evaluator : QA post-diag SANS nouveau Phase1 = ré-éval v2
        spec_v2 = EvaluatorSpec(criteria=[CriterionSpec(name="non_empty", gate=True)])
        events = (simple_pass("t1", success=False)
                  + [diag("t1", "ag", "evaluator"), qa("t1", "ag", success=True, spec=spec_v2)])
        r = _parse_runs(events)["t1"]
        assert len(r.passes) == 1
        assert r.reeval is not None and r.reeval.success is True
        assert r.reeval.spec.criteria[0].name == "non_empty"
        assert r.succeeded is True       # la ré-éval valide l'output original

    def test_reeval_fail_then_retry(self):
        events = (simple_pass("t1", success=False)
                  + [diag("t1", "ag", "evaluator", consignes="clarify"), qa("t1", "ag", success=False)]
                  + simple_pass("t1", success=True))
        r = _parse_runs(events)["t1"]
        assert r.reeval is not None and r.reeval.success is False
        assert len(r.passes) == 2
        assert r.succeeded is True

    def test_roster_gap_task(self):
        events = [RosterGapEvent(session_id=SID, task_id="t1", missing_tags=["legal"])]
        r = _parse_runs(events)["t1"]
        assert r.roster_gap is not None
        assert r.passes == []
        assert r.succeeded is False

    def test_unassigned_then_divided(self):
        events = ([p1("t1", "ag", passed=False),
                   UnassignedEvent(session_id=SID, task_id="t1", reason="no claim"),
                   divided("t1", [("s1", "part A", [], {"python": 50})])]
                  + simple_pass("s1"))
        runs = _parse_runs(events)
        assert runs["t1"].divided is not None
        assert runs["t1"].passes[0].outcome == "unassigned"
        assert runs["s1"].succeeded is True


class TestBuildTree:
    def test_root_from_meta(self):
        events = simple_pass("t1")
        tree = _build_tree(events, meta("t1", "do it"))
        assert tree.root_id == "t1"
        assert tree.children("t1") == []

    def test_recursive_tree_from_all_divided_events(self):
        events = (
            [p1("root", "ag", passed=False), UnassignedEvent(session_id=SID, task_id="root", reason="r"),
             divided("root", [("c1", "part 1", [], {"python": 50}), ("c2", "part 2", [], {"python": 50})])]
            + [p1("c1", "ag", passed=False), UnassignedEvent(session_id=SID, task_id="c1", reason="r"),
               divided("c1", [("g1", "deep 1", [], {"python": 50})])]
            + simple_pass("g1") + simple_pass("c2")
            + [aggregated("root", ["c1", "c2"])]
        )
        tree = _build_tree(events, meta("root", "big"))
        assert tree.root_id == "root"
        assert tree.children("root") == ["c1", "c2"]
        assert tree.children("c1") == ["g1"]
        assert tree.depth("g1") == 2
        assert tree.parent("g1") == "c1"
        assert tree.description("c1") == "part 1"

    def test_tasks_exported_on_graph_model(self):
        events = ([p1("root", "ag", passed=False), UnassignedEvent(session_id=SID, task_id="root", reason="r"),
                   divided("root", [("c1", "part 1", [], {"python": 50})])] + simple_pass("c1"))
        graph = build_graph(events, meta("root", "big"))
        by_id = {t.id: t for t in graph.tasks}
        assert by_id["root"].parent_id is None and by_id["root"].depth == 0
        assert by_id["c1"].parent_id == "root" and by_id["c1"].depth == 1
        assert by_id["c1"].description == "part 1"
        assert by_id["root"].description == "big"
