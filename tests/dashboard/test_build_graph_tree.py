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


def divided_fixture():
    """root unassigned → divisé en s1 (tool) et s2 (dépend de s1), agrégation réelle absente
    (s2 consomme s1, sink unique = s2 → court-circuit)."""
    return ([p1("root", "ag", passed=False),
             UnassignedEvent(session_id=SID, task_id="root", reason="no claim"),
             divided("root", [("s1", "investigate", [], {"python": 50}),
                              ("s2", "fix", ["s1"], {"python": 50})])]
            + simple_pass("s1", with_tool="grep", content="c1")
            + simple_pass("s2", content="c2"))


def divided_agg_fixture():
    """root → 2 sous-tâches indépendantes → 2 sinks → agrégation réelle."""
    return ([p1("root", "ag", passed=False),
             UnassignedEvent(session_id=SID, task_id="root", reason="no claim"),
             divided("root", [("s1", "part A", [], {"python": 50}),
                              ("s2", "part B", [], {"python": 50})])]
            + simple_pass("s1", content="c1") + simple_pass("s2", content="c2")
            + [aggregated("root", ["s1", "s2"])])


class TestStructure:
    def test_namespaced_nodes_simple_run(self):
        graph = build_graph(simple_pass("t1"), meta("t1", "do it"))
        ids = {n.id for n in graph.nodes}
        assert {"input", "tagger", "output", "dispatch:t1", "agent:t1:ag", "evaluator:t1"} <= ids
        assert "testset" not in ids                       # retiré du graphe série D
        agent = next(n for n in graph.nodes if n.type == "agent")
        assert agent.task_id == "t1" and agent.agent_id == "ag"

    def test_simple_run_edges_and_flows(self):
        graph = build_graph(simple_pass("t1"), meta("t1", "do it"))
        flows = {(e.from_node, e.to): e.flow for e in graph.edges}
        assert flows[("input", "tagger")] == "ascent"
        assert flows[("tagger", "dispatch:t1")] == "ascent"
        assert flows[("dispatch:t1", "agent:t1:ag")] == "ascent"
        assert flows[("agent:t1:ag", "evaluator:t1")] == "descent"
        assert flows[("evaluator:t1", "output")] == "descent"

    def test_tool_nodes_per_branch(self):
        graph = build_graph(simple_pass("t1", with_tool="grep"), meta("t1", "do it"))
        ids = {n.id for n in graph.nodes}
        assert "tool:t1:grep" in ids
        flows = {(e.from_node, e.to): e.flow for e in graph.edges}
        assert flows[("agent:t1:ag", "tool:t1:grep")] == "transient"

    def test_divided_short_circuit_no_aggregator(self):
        graph = build_graph(divided_fixture(), meta("root", "big"))
        ids = {n.id for n in graph.nodes}
        assert "divider:root" in ids and "aggregator:root" not in ids
        flows = {(e.from_node, e.to): e.flow for e in graph.edges}
        # division D1 : le dispatch raté monte vers le divider
        assert flows[("dispatch:root", "divider:root")] == "ascent"
        # bus d'émission : risers vers chaque branche
        assert flows[("divider:root", "dispatch:s1")] == "ascent"
        assert flows[("divider:root", "dispatch:s2")] == "ascent"
        # dep consommée : s1 → s2 en transient
        assert flows[("evaluator:s1", "dispatch:s2")] == "transient"
        # court-circuit : la descente du sink s2 file à OUTPUT
        assert flows[("evaluator:s2", "output")] == "descent"

    def test_divided_aggregated_structure(self):
        graph = build_graph(divided_agg_fixture(), meta("root", "big"))
        ids = {n.id for n in graph.nodes}
        assert "aggregator:root" in ids
        flows = {(e.from_node, e.to): e.flow for e in graph.edges}
        assert flows[("evaluator:s1", "aggregator:root")] == "descent"
        assert flows[("evaluator:s2", "aggregator:root")] == "descent"
        assert flows[("aggregator:root", "output")] == "descent"
        assert ("evaluator:s1", "output") not in flows

    def test_recursive_division_nested_pair(self):
        events = (
            [p1("root", "ag", passed=False), UnassignedEvent(session_id=SID, task_id="root", reason="r"),
             divided("root", [("c1", "part 1", [], {"python": 50}), ("c2", "part 2", [], {"python": 50})])]
            + [p1("c1", "ag", passed=False), UnassignedEvent(session_id=SID, task_id="c1", reason="r"),
               divided("c1", [("g1", "deep A", [], {"python": 50}), ("g2", "deep B", [], {"python": 50})])]
            + simple_pass("g1") + simple_pass("g2")
            + [aggregated("c1", ["g1", "g2"], content="c1 synth")]
            + simple_pass("c2")
            + [aggregated("root", ["c1", "c2"])]
        )
        graph = build_graph(events, meta("root", "big"))
        ids = {n.id for n in graph.nodes}
        assert {"divider:root", "aggregator:root", "divider:c1", "aggregator:c1"} <= ids
        flows = {(e.from_node, e.to): e.flow for e in graph.edges}
        # paire par niveau : l'aggregator enfant descend vers l'aggregator parent
        assert flows[("aggregator:c1", "aggregator:root")] == "descent"
        assert flows[("evaluator:g1", "aggregator:c1")] == "descent"


class TestSimpleRunWalk:
    def test_milestone_sequence_with_tagger(self):
        graph = build_graph(simple_pass("t1"), meta("t1", "do it"))
        assert [s.milestone_type for s in graph.steps] == [
            "input", "tagger", "dispatch", "agent", "evaluator", "output"]

    def test_no_tagger_without_required_tags(self):
        graph = build_graph(simple_pass("t1"), meta("t1", "do it", tags={}))
        types = [s.milestone_type for s in graph.steps]
        assert "tagger" not in types
        assert "tagger" not in {n.id for n in graph.nodes}

    def test_dispatch_milestone_namespaced(self):
        graph = build_graph(simple_pass("t1"), meta("t1", "do it"))
        d = next(s for s in graph.steps if s.milestone_type == "dispatch")
        assert "dispatch:t1" in d.active_nodes and "agent:t1:ag" in d.active_nodes
        pairs = {(e.from_node, e.to) for e in d.active_edges}
        assert ("tagger", "dispatch:t1") in pairs
        assert ("dispatch:t1", "agent:t1:ag") in pairs
        assert d.winner_agent_id == "ag" and d.pass_index == 0

    def test_evaluator_and_output(self):
        graph = build_graph(simple_pass("t1"), meta("t1", "do it"))
        ev = next(s for s in graph.steps if s.milestone_type == "evaluator")
        assert ev.outcome == "qa_pass" and ev.active_nodes == ["evaluator:t1"]
        out = graph.steps[-1]
        assert out.milestone_type == "output"
        pairs = {(e.from_node, e.to) for e in out.active_edges}
        assert ("evaluator:t1", "output") in pairs       # backbone cumulatif
        assert out.detail.output.output_content == "content"

    def test_tool_milestones_rle(self):
        evs = [p1("t1", "ag"), p2("t1", "ag"), disp("t1", "ag"),
               tool("t1", "ag", "grep"), tool("t1", "ag", "grep"), tool("t1", "ag", "read"),
               ex("t1", "ag"), qa("t1", "ag")]
        graph = build_graph(evs, meta("t1", "do it"))
        tool_steps = [s for s in graph.steps if s.milestone_type == "tool"]
        assert [s.detail.tool.tool_name for s in tool_steps] == ["grep", "read"]
        assert len(tool_steps[0].detail.tool.calls) == 2
        assert "tool:t1:grep" in tool_steps[0].active_nodes

    def test_qa_fail_no_output_milestone(self):
        # qa_fail SANS DiagnosedEvent (mode health check) : la branche s'arrête à l'evaluator
        graph = build_graph(simple_pass("t1", success=False), meta("t1", "do it"))
        assert graph.steps[-1].milestone_type == "evaluator"
        assert graph.steps[-1].outcome == "qa_fail"

    def test_unassigned_stops_at_dispatch(self):
        evs = [p1("t1", "ag", passed=False),
               UnassignedEvent(session_id=SID, task_id="t1", reason="no claim")]
        graph = build_graph(evs, meta("t1", "do it"))
        assert graph.steps[-1].milestone_type == "dispatch"
        assert graph.steps[-1].winner_agent_id is None
        assert graph.steps[-1].detail.dispatch.unassigned_reason == "no claim"


class TestDividedWalk:
    def test_sequence_short_circuit(self):
        # divided_fixture : s2 consomme s1 → sink unique s2 → PAS d'aggregator, OUTPUT depuis s2
        graph = build_graph(divided_fixture(), meta("root", "big"))
        types = [s.milestone_type for s in graph.steps]
        assert types == ["input", "tagger", "dispatch",                  # racine (unassigned)
                         "divider",
                         "dispatch", "tool", "agent", "evaluator",       # s1
                         "dispatch", "agent", "evaluator",               # s2
                         "output"]
        assert "aggregator" not in types
        out = graph.steps[-1]
        assert out.detail.output.output_content == "c2"                  # l'output du sink, pas une synthèse

    def test_sequence_aggregated(self):
        graph = build_graph(divided_agg_fixture(), meta("root", "big"))
        types = [s.milestone_type for s in graph.steps]
        assert types[-2:] == ["aggregator", "output"]
        agg = next(s for s in graph.steps if s.milestone_type == "aggregator")
        assert agg.detail.aggregator.aggregated is True
        assert agg.detail.aggregator.collected == 2 and agg.detail.aggregator.total == 2
        out = graph.steps[-1]
        assert out.detail.output.output_content == "final"

    def test_collect_story_on_sink_evaluator(self):
        graph = build_graph(divided_agg_fixture(), meta("root", "big"))
        ev1 = next(s for s in graph.steps if s.milestone_type == "evaluator" and s.sub_task_id == "s1")
        assert "aggregator:root" in ev1.active_nodes
        pairs = {(e.from_node, e.to) for e in ev1.active_edges}
        assert ("evaluator:s1", "aggregator:root") in pairs
        assert ev1.detail.aggregator.collected == 1 and ev1.detail.aggregator.total == 2

    def test_divider_milestone_carries_subtasks_and_origin(self):
        graph = build_graph(divided_agg_fixture(), meta("root", "big"))
        div = next(s for s in graph.steps if s.milestone_type == "divider")
        assert div.detail.divider.origin == "recovery"            # division D1 (unassigned)
        assert [st.id for st in div.detail.divider.sub_tasks] == ["s1", "s2"]
        assert div.detail.divider.sub_tasks[0].required_tags == {"python": 50}

    def test_recursive_walk_nested(self):
        # même fixture que test_recursive_division_nested_pair (Task 5)
        events = (
            [p1("root", "ag", passed=False), UnassignedEvent(session_id=SID, task_id="root", reason="r"),
             divided("root", [("c1", "part 1", [], {"python": 50}), ("c2", "part 2", [], {"python": 50})])]
            + [p1("c1", "ag", passed=False), UnassignedEvent(session_id=SID, task_id="c1", reason="r"),
               divided("c1", [("g1", "deep A", [], {"python": 50}), ("g2", "deep B", [], {"python": 50})])]
            + simple_pass("g1") + simple_pass("g2")
            + [aggregated("c1", ["g1", "g2"], content="c1 synth")]
            + simple_pass("c2")
            + [aggregated("root", ["c1", "c2"])]
        )
        graph = build_graph(events, meta("root", "big"))
        seq = [(s.milestone_type, s.sub_task_id) for s in graph.steps]
        # l'arbre se déroule en profondeur : c1 se divise AVANT que c2 ne tourne
        assert seq.index(("divider", "c1")) < seq.index(("dispatch", "c2"))
        assert seq.index(("aggregator", "c1")) < seq.index(("dispatch", "c2"))
        # deux aggregators, niveau enfant puis racine
        aggs = [s.sub_task_id for s in graph.steps if s.milestone_type == "aggregator"]
        assert aggs == ["c1", "root"]
        # le step detail de chaque sous-branche est scopé
        a_g1 = next(s for s in graph.steps if s.milestone_type == "agent" and s.sub_task_id == "g1")
        assert a_g1.detail.input.description == "deep A"

    def test_subtask_unassigned_no_recovery(self):
        # une sous-tâche unassigned NON divisée (gap de claim) : sa branche s'arrête au dispatch
        events = ([p1("root", "ag", passed=False),
                   UnassignedEvent(session_id=SID, task_id="root", reason="r"),
                   divided("root", [("s1", "ok", [], {"python": 50}),
                                    ("s2", "nobody", [], {"python": 50})])]
                  + simple_pass("s1")
                  + [p1("s2", "ag", passed=False),
                     UnassignedEvent(session_id=SID, task_id="s2", reason="no claim")])
        graph = build_graph(events, meta("root", "big"))
        s2_types = [s.milestone_type for s in graph.steps if s.sub_task_id == "s2"]
        assert s2_types == ["dispatch"]
        # s1 est l'unique sink → court-circuit → OUTPUT depuis s1
        assert graph.steps[-1].milestone_type == "output"
        assert graph.steps[-1].detail.output.output_content == "content"


class TestD3Walk:
    def test_route_agent_retry(self):
        events = (simple_pass("t1", success=False)
                  + [diag("t1", "ag", "agent", reason="weak", consignes="be precise")]
                  + simple_pass("t1", success=True, content="fixed"))
        graph = build_graph(events, meta("t1", "do it"))
        types = [(s.milestone_type, s.pass_index) for s in graph.steps]
        assert types == [("input", 0), ("tagger", 0),
                         ("dispatch", 0), ("agent", 0), ("evaluator", 0),
                         ("diagnostic", 0),
                         ("dispatch", 1), ("agent", 1), ("evaluator", 1),
                         ("output", 0)]
        dg = next(s for s in graph.steps if s.milestone_type == "diagnostic")
        assert dg.outcome == "diagnosed"
        assert dg.label == "DIAGNOSTIC · route agent"
        assert dg.detail.diagnostic.attribution == "agent"
        assert dg.detail.diagnostic.consignes == "be precise"
        # le loop-back diag→dispatch s'allume au DISPATCH pass 2
        d2 = next(s for s in graph.steps if s.milestone_type == "dispatch" and s.pass_index == 1)
        assert d2.label == "DISPATCH · pass 2"
        pairs = {(e.from_node, e.to, e.flow) for e in d2.active_edges}
        assert ("diagnostic:t1", "dispatch:t1", "transient") in pairs
        # l'output final vient de la passe 2
        assert graph.steps[-1].detail.output.output_content == "fixed"

    def test_route_evaluator_reeval_success(self):
        spec_v2 = EvaluatorSpec(criteria=[CriterionSpec(name="non_empty", gate=True)])
        events = (simple_pass("t1", success=False)
                  + [diag("t1", "ag", "evaluator", reason="strict"),
                     qa("t1", "ag", success=True, spec=spec_v2)])
        graph = build_graph(events, meta("t1", "do it"))
        types = [s.milestone_type for s in graph.steps]
        assert types == ["input", "tagger", "dispatch", "agent", "evaluator",
                         "diagnostic", "evaluator", "output"]
        v2 = [s for s in graph.steps if s.milestone_type == "evaluator"][1]
        assert v2.label == "EVALUATOR v2"
        assert v2.outcome == "qa_pass"
        assert v2.detail.evaluator.spec.criteria[0].name == "non_empty"   # spec régénérée
        v1 = [s for s in graph.steps if s.milestone_type == "evaluator"][0]
        assert v1.detail.evaluator.spec is None                            # specs v1/v2 distinctes
        # l'output final est l'output ORIGINAL (validé par la spec v2)
        assert graph.steps[-1].detail.output.output_content == "content"

    def test_route_evaluator_reeval_fail_then_retry(self):
        events = (simple_pass("t1", success=False)
                  + [diag("t1", "ag", "evaluator", consignes="clarify"), qa("t1", "ag", success=False)]
                  + simple_pass("t1", success=True, content="recovered"))
        graph = build_graph(events, meta("t1", "do it"))
        types = [s.milestone_type for s in graph.steps]
        assert types == ["input", "tagger", "dispatch", "agent", "evaluator",
                         "diagnostic", "evaluator",
                         "dispatch", "agent", "evaluator", "output"]
        assert graph.steps[-1].detail.output.output_content == "recovered"

    def test_route_task_spec_division_origin_diagnostic(self):
        events = (simple_pass("root", success=False)
                  + [diag("root", "ag", "task_spec", reason="ambiguous"),
                     divided("root", [("s1", "part A", [], {"python": 50}),
                                      ("s2", "part B", [], {"python": 50})])]
                  + simple_pass("s1") + simple_pass("s2")
                  + [aggregated("root", ["s1", "s2"])])
        graph = build_graph(events, meta("root", "big"))
        div = next(s for s in graph.steps if s.milestone_type == "divider")
        assert div.detail.divider.origin == "diagnostic"
        # l'arête de division part du DIAG, pas du dispatch
        flows = {(e.from_node, e.to): e.flow for e in graph.edges}
        assert flows[("diagnostic:root", "divider:root")] == "ascent"
        assert ("dispatch:root", "divider:root") not in flows
        # séquence : ... evaluator (fail) → diagnostic → divider → branches → aggregator → output
        types = [s.milestone_type for s in graph.steps]
        i = types.index("diagnostic")
        assert types[i + 1] == "divider"

    def test_route_unattributed_stops(self):
        events = simple_pass("t1", success=False) + [diag("t1", "ag", "unattributed", reason="")]
        graph = build_graph(events, meta("t1", "do it"))
        dg = graph.steps[-1]
        assert dg.milestone_type == "diagnostic"
        assert dg.label == "DIAGNOSTIC · route stop"
        assert dg.detail.diagnostic.route_taken == "stop"
        # pas d'output : la branche meurt au diagnostic
        assert all(s.milestone_type != "output" for s in graph.steps)

    def test_diagnostic_node_and_edges_static(self):
        events = (simple_pass("t1", success=False)
                  + [diag("t1", "ag", "agent", consignes="x")]
                  + simple_pass("t1", success=True))
        graph = build_graph(events, meta("t1", "do it"))
        ids = {n.id for n in graph.nodes}
        assert "diagnostic:t1" in ids
        n = next(n for n in graph.nodes if n.id == "diagnostic:t1")
        assert n.type == "diagnostic"
        flows = {(e.from_node, e.to): e.flow for e in graph.edges}
        assert flows[("evaluator:t1", "diagnostic:t1")] == "descent"
        assert flows[("diagnostic:t1", "dispatch:t1")] == "transient"


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
