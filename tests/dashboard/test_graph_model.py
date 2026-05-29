from aaosa.schemas.output import LLMMetadata
from aaosa.qa.judge import JudgeBreakdown, DimensionScore
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
)


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
