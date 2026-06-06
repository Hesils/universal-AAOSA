from aaosa.tracing.events import (
    DividedSubTask,
    DispatchedEvent,
    ExecutedEvent,
    Phase1FilteredEvent,
    QAEvaluatedEvent,
    TaskAggregatedEvent,
    TaskDividedEvent,
)
from aaosa.tracing.store import SessionMeta, SessionTaskRecord
from dashboard.graph_model import build_graph

SID, P = "sess-d2", "parent"


def _meta():
    return SessionMeta(
        session_id=SID, started_at="2026-01-01T00:00:00Z", ended_at="2026-01-01T00:01:00Z",
        tasks=[SessionTaskRecord(id=P, description="incident", winner_agent_id=None, outcome="divided", required_tags={})],
        agent_ids=["ag"],
    )


def _sub(task_id, content, success=True):
    return [
        Phase1FilteredEvent(session_id=SID, task_id=task_id, agent_id="ag", passed=True, fit_score=0.9),
        DispatchedEvent(session_id=SID, task_id=task_id, agent_id="ag", reason="sole claimer"),
        ExecutedEvent(session_id=SID, task_id=task_id, agent_id="ag", output_summary=content, output_content=content),
        QAEvaluatedEvent(session_id=SID, task_id=task_id, agent_id="ag", success=success, score=1.0 if success else 0.0, reason="r"),
    ]


def _single_sink_chain_events():
    """investigate -> fix (fix dépend d'investigate), tous deux réussis, AUCUNE agrégation
    (court-circuit : un seul sink = fix)."""
    S1, S2 = "s1", "s2"
    return [
        TaskDividedEvent(session_id=SID, task_id=P, sub_tasks=[
            DividedSubTask(id=S1, description="investigate", depends_on=[]),
            DividedSubTask(id=S2, description="fix", depends_on=[S1]),
        ]),
        *_sub(S1, "c1"),
        *_sub(S2, "c2"),
        # pas de TaskAggregatedEvent
    ]


def _multi_sink_with_intermediate_events():
    """investigate -> analyze (analyze dépend d'investigate) + check (indépendant).
    Sinks = {analyze, check} ; investigate est consommé, donc PAS un sink."""
    S1, S2, S3 = "s1", "s2", "s3"
    return [
        TaskDividedEvent(session_id=SID, task_id=P, sub_tasks=[
            DividedSubTask(id=S1, description="investigate", depends_on=[]),
            DividedSubTask(id=S2, description="analyze", depends_on=[S1]),
            DividedSubTask(id=S3, description="check", depends_on=[]),
        ]),
        *_sub(S1, "c1"),
        *_sub(S2, "c2"),
        *_sub(S3, "c3"),
        TaskAggregatedEvent(session_id=SID, task_id=P, sub_task_ids=["s2", "s3"],
                            output_summary="final", output_content="final report"),
    ]


class TestSingleSinkCourtCircuit:
    def test_no_aggregator_node(self):
        graph = build_graph(_single_sink_chain_events(), _meta())
        assert "aggregator" not in {n.id for n in graph.nodes}

    def test_no_aggregator_milestone_terminal_is_output(self):
        graph = build_graph(_single_sink_chain_events(), _meta())
        types = [s.milestone_type for s in graph.steps]
        assert "aggregator" not in types
        assert types[-1] == "output"

    def test_output_comes_from_the_sink(self):
        graph = build_graph(_single_sink_chain_events(), _meta())
        out = graph.steps[-1]
        assert out.detail.output.output_content == "c2"   # fix = le sink
        pairs = {(e.from_node, e.to) for e in out.active_edges}
        assert ("evaluator:s2", "output") in pairs


class TestMultiSinkWithConsumedIntermediate:
    def test_consumed_intermediate_does_not_feed_aggregator(self):
        graph = build_graph(_multi_sink_with_intermediate_events(), _meta())
        ev_by_sub = {s.sub_task_id: s for s in graph.steps if s.milestone_type == "evaluator"}
        # investigate (s1) est consommé par analyze (s2) -> pas un sink -> n'allume pas l'aggregator
        assert "aggregator:parent" not in ev_by_sub["s1"].active_nodes
        # analyze (s2) et check (s3) sont des sinks -> allument l'aggregator
        assert "aggregator:parent" in ev_by_sub["s2"].active_nodes
        assert "aggregator:parent" in ev_by_sub["s3"].active_nodes

    def test_total_and_collected_count_sinks(self):
        graph = build_graph(_multi_sink_with_intermediate_events(), _meta())
        agg = next(s for s in graph.steps if s.milestone_type == "aggregator")
        assert agg.detail.aggregator.total == 2          # 2 sinks, pas 3 sous-tâches
        assert agg.detail.aggregator.collected == 2
        assert agg.detail.aggregator.sub_task_ids == ["s2", "s3"]
