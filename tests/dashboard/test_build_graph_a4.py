from aaosa.tracing.events import (
    ExecutedEvent,
    Phase1FilteredEvent,
    Phase2ClaimedEvent,
    DispatchedEvent,
    TaskAggregatedEvent,
    TaskDividedEvent,
)
from dashboard.graph_model import build_graph

SID = "sess-1"
PARENT = "parent-task"
SUB1 = "sub-1"


def _divided_events():
    """A parent task that was divided, plus one sub-task that ran normally."""
    return [
        TaskDividedEvent(session_id=SID, task_id=PARENT, sub_task_ids=[SUB1]),
        Phase1FilteredEvent(session_id=SID, task_id=SUB1, agent_id="ag-1", passed=True, fit_score=0.9),
        Phase2ClaimedEvent(session_id=SID, task_id=SUB1, agent_id="ag-1", decision="claim", justification="mine"),
        DispatchedEvent(session_id=SID, task_id=SUB1, agent_id="ag-1", reason="sole claimer"),
        ExecutedEvent(session_id=SID, task_id=SUB1, agent_id="ag-1", output_summary="o", output_content="o"),
        TaskAggregatedEvent(
            session_id=SID, task_id=PARENT, sub_task_ids=[SUB1],
            output_summary="synth", output_content="synthesized",
        ),
    ]


class TestBuildGraphA4:
    def test_build_graph_divided_task_has_divider_node(self):
        graph = build_graph(_divided_events())
        node_ids = {n.id for n in graph.nodes}
        assert "divider" in node_ids
        assert "aggregator" in node_ids

    def test_build_graph_divided_step_outcome_is_divided(self):
        graph = build_graph(_divided_events())
        parent_step = next(s for s in graph.steps if s.task_id == PARENT)
        assert parent_step.outcome == "divided"
        assert parent_step.winner_agent_id is None
        assert parent_step.detail.output.output_content == "synthesized"

    def test_build_graph_divided_active_path(self):
        graph = build_graph(_divided_events())
        parent_step = next(s for s in graph.steps if s.task_id == PARENT)
        assert parent_step.active_nodes == ["input", "divider", "aggregator", "output"]
