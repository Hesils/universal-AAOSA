from aaosa.tracing.events import (
    DividedSubTask,
    ExecutedEvent,
    Phase1FilteredEvent,
    Phase2ClaimedEvent,
    DispatchedEvent,
    QAEvaluatedEvent,
    TaskAggregatedEvent,
    TaskDividedEvent,
)
from aaosa.tracing.store import SessionMeta, SessionTaskRecord
from dashboard.graph_model import build_graph

SID, PARENT, SUB1 = "sess-1", "parent-task", "sub-1"


def _meta():
    return SessionMeta(
        session_id=SID, started_at="2026-01-01T00:00:00Z", ended_at="2026-01-01T00:01:00Z",
        tasks=[SessionTaskRecord(id=PARENT, description="parent", winner_agent_id=None, outcome="divided", required_tags={})],
        agent_ids=["ag-1"],
    )


def _divided_events():
    return [
        TaskDividedEvent(session_id=SID, task_id=PARENT,
                         sub_tasks=[DividedSubTask(id=SUB1, description="sub", depends_on=[])]),
        Phase1FilteredEvent(session_id=SID, task_id=SUB1, agent_id="ag-1", passed=True, fit_score=0.9),
        Phase2ClaimedEvent(session_id=SID, task_id=SUB1, agent_id="ag-1", decision="claim", justification="mine"),
        DispatchedEvent(session_id=SID, task_id=SUB1, agent_id="ag-1", reason="sole claimer"),
        ExecutedEvent(session_id=SID, task_id=SUB1, agent_id="ag-1", output_summary="o", output_content="o"),
        QAEvaluatedEvent(session_id=SID, task_id=SUB1, agent_id="ag-1", success=True, score=1.0, reason="r"),
        TaskAggregatedEvent(session_id=SID, task_id=PARENT, sub_task_ids=[SUB1],
                            output_summary="synth", output_content="synthesized"),
    ]


class TestBuildGraphA4:
    def test_divided_has_divider_and_aggregator_nodes(self):
        ids = {n.id for n in build_graph(_divided_events(), _meta()).nodes}
        assert "divider:parent-task" in ids and "aggregator:parent-task" in ids

    def test_divided_milestone_sequence(self):
        # required_tags={} → no tagger
        types = [s.milestone_type for s in build_graph(_divided_events(), _meta()).steps]
        assert types == ["input", "divider", "dispatch", "agent", "evaluator", "aggregator", "output"]

    def test_output_carries_aggregated_content(self):
        out = build_graph(_divided_events(), _meta()).steps[-1]
        assert out.detail.output.output_content == "synthesized"
