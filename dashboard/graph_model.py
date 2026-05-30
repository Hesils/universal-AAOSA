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
    context: str | None = None


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


def _agent_ids(events: list[ClaimEvent]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for e in events:
        aid = getattr(e, "agent_id", None)
        if aid is not None and aid not in seen:
            seen.add(aid)
            ordered.append(aid)
    return ordered


def _build_nodes(events: list[ClaimEvent]) -> list[GraphNode]:
    nodes = [
        GraphNode(id="input", layer="top", type="input", label="Input"),
        GraphNode(id="dispatch", layer="center", type="dispatch", label="Dispatch"),
        GraphNode(id="evaluator", layer="center", type="evaluator", label="Evaluator"),
        GraphNode(id="output", layer="top", type="output", label="Output"),
        GraphNode(id="testset", layer="top", type="testset", label="TestSet"),
    ]
    for aid in _agent_ids(events):
        nodes.append(GraphNode(id=aid, layer="bottom", type="agent", label=aid))
    return nodes


def _build_edges(nodes: list[GraphNode]) -> list[GraphEdge]:
    agent_ids = [n.id for n in nodes if n.type == "agent"]
    edges = [GraphEdge(from_node="input", to="dispatch")]
    edges += [GraphEdge(from_node="dispatch", to=aid) for aid in agent_ids]
    edges += [GraphEdge(from_node=aid, to="evaluator") for aid in agent_ids]
    edges += [GraphEdge(from_node=aid, to="output") for aid in agent_ids]
    edges.append(GraphEdge(from_node="evaluator", to="output"))
    edges.append(GraphEdge(from_node="evaluator", to="testset"))
    return edges


def _events_by_task(events: list[ClaimEvent]) -> dict[str, list[ClaimEvent]]:
    out: dict[str, list[ClaimEvent]] = {}
    for e in events:
        out.setdefault(e.task_id, []).append(e)
    return out


def _meta_record(session_meta: SessionMeta | None, task_id: str) -> SessionTaskRecord | None:
    if session_meta is None:
        return None
    for rec in session_meta.tasks:
        if rec.id == task_id:
            return rec
    return None


def _order_task_ids(events: list[ClaimEvent], session_meta: SessionMeta | None) -> list[str]:
    present = {e.task_id for e in events}
    if session_meta is not None:
        return [rec.id for rec in session_meta.tasks if rec.id in present]
    first_ts: dict[str, object] = {}
    for e in events:
        if e.task_id not in first_ts:
            first_ts[e.task_id] = e.timestamp
    return sorted(first_ts, key=lambda tid: first_ts[tid])


def _active_path(outcome: Outcome, winner_id: str | None) -> tuple[list[str], list[GraphEdge]]:
    nodes = ["input", "dispatch"]
    edges = [GraphEdge(from_node="input", to="dispatch")]
    if outcome == "unassigned" or winner_id is None:
        return nodes, edges
    nodes.append(winner_id)
    edges.append(GraphEdge(from_node="dispatch", to=winner_id))
    if outcome == "no_qa":
        nodes.append("output")
        edges.append(GraphEdge(from_node=winner_id, to="output"))
        return nodes, edges
    nodes.append("evaluator")
    edges.append(GraphEdge(from_node=winner_id, to="evaluator"))
    if outcome == "qa_pass":
        nodes.append("output")
        edges.append(GraphEdge(from_node="evaluator", to="output"))
    else:  # qa_fail
        nodes.append("testset")
        edges.append(GraphEdge(from_node="evaluator", to="testset"))
    return nodes, edges


def _build_step(task_id: str, run: list[ClaimEvent], meta_record: SessionTaskRecord | None) -> GraphStep:
    phase1 = [e for e in run if isinstance(e, Phase1FilteredEvent)]
    phase2 = {e.agent_id: e for e in run if isinstance(e, Phase2ClaimedEvent)}
    dispatched = next((e for e in run if isinstance(e, DispatchedEvent)), None)
    unassigned_ev = next((e for e in run if isinstance(e, UnassignedEvent)), None)
    executed = next((e for e in run if isinstance(e, ExecutedEvent)), None)
    qa_ev = next((e for e in run if isinstance(e, QAEvaluatedEvent)), None)
    elo_ev = next((e for e in run if isinstance(e, EloUpdatedEvent)), None)
    tag_evs = [e for e in run if isinstance(e, TagAcquiredEvent)]

    winner_id = dispatched.agent_id if dispatched is not None else None

    if unassigned_ev is not None or dispatched is None:
        outcome: Outcome = "unassigned"
    elif qa_ev is None:
        outcome = "no_qa"
    elif qa_ev.success:
        outcome = "qa_pass"
    else:
        outcome = "qa_fail"

    dispatch_detail = DispatchDetail(
        candidates=[CandidateInfo(agent_id=e.agent_id, passed=e.passed, fit_score=e.fit_score) for e in phase1],
        claims=[ClaimInfo(agent_id=e.agent_id, decision=e.decision, justification=e.justification) for e in phase2.values()],
        winner_agent_id=winner_id,
        dispatch_reason=dispatched.reason if dispatched is not None else None,
        unassigned_reason=unassigned_ev.reason if unassigned_ev is not None else None,
    )

    agents: dict[str, AgentDetail] = {}
    for e in phase1:
        aid = e.agent_id
        claim = phase2.get(aid)
        is_winner = aid == winner_id
        agents[aid] = AgentDetail(
            agent_id=aid,
            role="winner" if is_winner else "candidate",
            passed=e.passed,
            fit_score=e.fit_score,
            claim_decision=claim.decision if claim is not None else None,
            justification=claim.justification if claim is not None else None,
            output_summary=executed.output_summary if (is_winner and executed is not None) else None,
            output_content=executed.output_content if (is_winner and executed is not None) else None,
            llm_metadata=executed.llm_metadata if (is_winner and executed is not None) else None,
            elo_deltas=dict(elo_ev.deltas) if (is_winner and elo_ev is not None) else {},
            tags_acquired=[TagAcquiredInfo(tag=t.tag, initial_elo=t.initial_elo) for t in tag_evs] if is_winner else [],
        )

    if qa_ev is not None:
        evaluator_detail = EvaluatorDetail(
            ran=True, success=qa_ev.success, score=qa_ev.score, reason=qa_ev.reason,
            criteria_results=dict(qa_ev.criteria_results), judge=qa_ev.judge,
        )
    else:
        evaluator_detail = EvaluatorDetail(
            ran=False, success=None, score=None, reason=None,
            criteria_results={}, judge=None,
        )

    if executed is not None:
        output_detail = OutputDetail(
            produced=True, output_summary=executed.output_summary,
            output_content=executed.output_content, llm_metadata=executed.llm_metadata,
        )
    else:
        output_detail = OutputDetail(produced=False, output_summary=None, output_content=None, llm_metadata=None)

    testset_detail = TestSetDetail(forked=(outcome == "qa_fail"), from_task_id=task_id)

    description = meta_record.description if meta_record is not None else task_id
    required_tags = dict(meta_record.required_tags) if meta_record is not None else {}
    context = meta_record.context if meta_record is not None else None
    input_detail = InputDetail(task_id=task_id, description=description, required_tags=required_tags, context=context)

    active_nodes, active_edges = _active_path(outcome, winner_id)

    return GraphStep(
        task_id=task_id,
        label=description,
        active_nodes=active_nodes,
        active_edges=active_edges,
        winner_agent_id=winner_id,
        outcome=outcome,
        detail=StepDetail(
            input=input_detail,
            dispatch=dispatch_detail,
            agents=agents,
            evaluator=evaluator_detail,
            output=output_detail,
            testset=testset_detail,
        ),
    )


def build_graph(events: list[ClaimEvent], session_meta: SessionMeta | None = None) -> GraphModel:
    nodes = _build_nodes(events)
    edges = _build_edges(nodes)
    by_task = _events_by_task(events)
    steps = [
        _build_step(tid, _segment_runs(by_task[tid]), _meta_record(session_meta, tid))
        for tid in _order_task_ids(events, session_meta)
    ]
    return GraphModel(nodes=nodes, edges=edges, steps=steps)
