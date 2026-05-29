from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from aaosa.qa.judge import JudgeBreakdown
from aaosa.schemas.output import LLMMetadata
from aaosa.tracing.events import (
    ClaimEvent,
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

NodeLayer = Literal["top", "center", "bottom"]
NodeType = Literal["input", "dispatch", "evaluator", "output", "testset", "agent"]
Outcome = Literal["qa_pass", "qa_fail", "unassigned", "no_qa"]


class GraphNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    layer: NodeLayer
    type: NodeType
    label: str


class GraphEdge(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    from_node: str = Field(alias="from")
    to: str


class CandidateInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str
    passed: bool
    fit_score: float


class ClaimInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str
    decision: Literal["claim", "no_claim"]
    justification: str


class DispatchDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidates: list[CandidateInfo]
    claims: list[ClaimInfo]
    winner_agent_id: str | None
    dispatch_reason: str | None
    unassigned_reason: str | None


class TagAcquiredInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tag: str
    initial_elo: int


class AgentDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str
    role: Literal["winner", "candidate"]
    passed: bool
    fit_score: float
    claim_decision: Literal["claim", "no_claim"] | None
    justification: str | None
    output_summary: str | None
    output_content: str | None
    llm_metadata: LLMMetadata | None
    elo_deltas: dict[str, int]
    tags_acquired: list[TagAcquiredInfo]


class EvaluatorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ran: bool
    success: bool | None
    score: float | None
    reason: str | None
    criteria_results: dict[str, bool]
    judge: JudgeBreakdown | None


class InputDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str
    description: str
    required_tags: dict[str, int]


class OutputDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    produced: bool
    output_summary: str | None
    output_content: str | None
    llm_metadata: LLMMetadata | None


class TestSetDetail(BaseModel):
    __test__ = False
    model_config = ConfigDict(extra="forbid")
    forked: bool
    from_task_id: str


class StepDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input: InputDetail
    dispatch: DispatchDetail
    agents: dict[str, AgentDetail]
    evaluator: EvaluatorDetail
    output: OutputDetail
    testset: TestSetDetail


class GraphStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str
    label: str
    active_nodes: list[str]
    active_edges: list[GraphEdge]
    winner_agent_id: str | None
    outcome: Outcome
    detail: StepDetail


class GraphModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    steps: list[GraphStep]


def _segment_runs(task_events: list[ClaimEvent]) -> list[ClaimEvent]:
    """Keeps only the last run for a given task_id.

    A new run starts when a Phase1FilteredEvent appears after a non-Phase1FilteredEvent.
    No-op in session (1 run), keeps last of N runs in health check.
    """
    runs: list[list[ClaimEvent]] = []
    current: list[ClaimEvent] = []
    for e in task_events:
        if isinstance(e, Phase1FilteredEvent) and current and not isinstance(current[-1], Phase1FilteredEvent):
            runs.append(current)
            current = []
        current.append(e)
    if current:
        runs.append(current)
    return runs[-1] if runs else []


def build_graph(events: list[ClaimEvent], session_meta: SessionMeta | None = None) -> GraphModel:
    raise NotImplementedError
