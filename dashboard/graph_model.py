from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from aaosa.qa.judge import JudgeBreakdown
from aaosa.qa.spec import EvaluatorSpec
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
    TaskAggregatedEvent,
    TaskDividedEvent,
    ToolCalledEvent,
    UnassignedEvent,
)
from aaosa.tracing.store import SessionMeta, SessionTaskRecord

NodeLayer = Literal["tools", "bottom", "center", "top"]
NodeType = Literal["input", "dispatch", "evaluator", "output", "testset", "agent", "divider", "aggregator", "tool"]
MilestoneType = Literal["input", "divider", "dispatch", "agent", "tool", "evaluator", "aggregator", "output"]
Outcome = Literal["qa_pass", "qa_fail", "unassigned", "no_qa", "divided"]


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
    candidates: list[CandidateInfo] = Field(default_factory=list)
    claims: list[ClaimInfo] = Field(default_factory=list)
    winner_agent_id: str | None = None
    dispatch_reason: str | None = None
    unassigned_reason: str | None = None


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
    elo_deltas: dict[str, int] = Field(default_factory=dict)
    tags_acquired: list[TagAcquiredInfo] = Field(default_factory=list)
    tool_calls: list["ToolCallInfo"] = Field(default_factory=list)


class EvaluatorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ran: bool
    success: bool | None
    score: float | None
    reason: str | None
    criteria_results: dict[str, bool] = Field(default_factory=dict)
    judge: JudgeBreakdown | None = None
    spec: EvaluatorSpec | None = None


class InputDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str
    description: str
    required_tags: dict[str, int] = Field(default_factory=dict)
    context: str | None = None


class OutputDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    produced: bool
    output_summary: str | None = None
    output_content: str | None = None
    llm_metadata: LLMMetadata | None = None


class TestSetDetail(BaseModel):
    __test__ = False
    model_config = ConfigDict(extra="forbid")
    forked: bool
    from_task_id: str


class DividerSubTaskInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    description: str
    depends_on: list[str] = Field(default_factory=list)


class DividerDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    divided: bool
    sub_tasks: list[DividerSubTaskInfo] = Field(default_factory=list)


class AggregatorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    aggregated: bool
    sub_task_ids: list[str] = Field(default_factory=list)
    output_summary: str | None = None
    output_content: str | None = None


class ToolCallInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool_name: str
    arguments: dict = Field(default_factory=dict)
    result: str
    latency_ms: float


class ToolDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str | None
    tool_name: str
    calls: list[ToolCallInfo] = Field(default_factory=list)


class StepDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input: InputDetail
    dispatch: DispatchDetail = Field(default_factory=lambda: DispatchDetail())
    agents: dict[str, AgentDetail] = Field(default_factory=dict)
    evaluator: EvaluatorDetail = Field(
        default_factory=lambda: EvaluatorDetail(ran=False, success=None, score=None, reason=None)
    )
    output: OutputDetail = Field(default_factory=lambda: OutputDetail(produced=False))
    testset: TestSetDetail = Field(default_factory=lambda: TestSetDetail(forked=False, from_task_id=""))
    divider: DividerDetail = Field(default_factory=lambda: DividerDetail(divided=False))
    aggregator: AggregatorDetail = Field(default_factory=lambda: AggregatorDetail(aggregated=False))
    tool: ToolDetail | None = None

    @classmethod
    def empty(cls, task_id: str, description: str) -> "StepDetail":
        return cls(input=InputDetail(task_id=task_id, description=description))


class TodoItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    description: str
    state: Literal["pending", "current", "done", "failed"]
    is_root: bool


class GraphStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    milestone_type: MilestoneType
    label: str
    sub_task_id: str | None = None
    order_index: int | None = None
    active_nodes: list[str] = Field(default_factory=list)
    active_edges: list[GraphEdge] = Field(default_factory=list)
    winner_agent_id: str | None = None
    outcome: Outcome = "no_qa"
    detail: StepDetail
    todo: list[TodoItem] = Field(default_factory=list)


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


def _tool_node_id(tool_name: str) -> str:
    return "tool:" + tool_name


def _distinct_tools(events: list[ClaimEvent]) -> list[tuple[str, str]]:
    """(agent_id, tool_name) distincts, dans l'ordre d'apparition."""
    seen: set[tuple[str, str]] = set()
    ordered: list[tuple[str, str]] = []
    for e in events:
        if isinstance(e, ToolCalledEvent):
            key = (e.agent_id, e.tool_name)
            if key not in seen:
                seen.add(key)
                ordered.append(key)
    return ordered


def _build_nodes(events: list[ClaimEvent]) -> list[GraphNode]:
    nodes = [
        GraphNode(id="input", layer="top", type="input", label="Input"),
        GraphNode(id="dispatch", layer="center", type="dispatch", label="Dispatch"),
        GraphNode(id="evaluator", layer="center", type="evaluator", label="Evaluator"),
        GraphNode(id="output", layer="top", type="output", label="Output"),
        GraphNode(id="testset", layer="top", type="testset", label="TestSet"),
    ]
    if any(isinstance(e, TaskDividedEvent) for e in events):
        nodes.append(GraphNode(id="divider", layer="center", type="divider", label="Divider"))
        nodes.append(GraphNode(id="aggregator", layer="center", type="aggregator", label="Aggregator"))
    for aid in _agent_ids(events):
        nodes.append(GraphNode(id=aid, layer="bottom", type="agent", label=aid))
    seen_tools: set[str] = set()
    for _aid, tname in _distinct_tools(events):
        if tname not in seen_tools:
            seen_tools.add(tname)
            nodes.append(GraphNode(id=_tool_node_id(tname), layer="tools", type="tool", label=tname))
    return nodes


def _build_edges(nodes: list[GraphNode], events: list[ClaimEvent]) -> list[GraphEdge]:
    agent_ids = [n.id for n in nodes if n.type == "agent"]
    edges = [GraphEdge(from_node="input", to="dispatch")]
    edges += [GraphEdge(from_node="dispatch", to=aid) for aid in agent_ids]
    edges += [GraphEdge(from_node=aid, to="evaluator") for aid in agent_ids]
    edges += [GraphEdge(from_node=aid, to="output") for aid in agent_ids]
    edges.append(GraphEdge(from_node="evaluator", to="output"))
    edges.append(GraphEdge(from_node="evaluator", to="testset"))
    for aid, tname in _distinct_tools(events):
        edges.append(GraphEdge(from_node=aid, to=_tool_node_id(tname)))
    if any(n.id == "divider" for n in nodes):
        edges.append(GraphEdge(from_node="input", to="divider"))
        edges.append(GraphEdge(from_node="divider", to="aggregator"))
        edges.append(GraphEdge(from_node="aggregator", to="output"))
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


def _make_input_detail(meta_record: SessionTaskRecord | None, task_id: str) -> InputDetail:
    if meta_record is not None:
        return InputDetail(
            task_id=task_id, description=meta_record.description,
            required_tags=dict(meta_record.required_tags), context=meta_record.context,
        )
    return InputDetail(task_id=task_id, description=task_id)


def _agent_detail(aid, phase1_by_agent, phase2_by_agent, winner_id, executed, elo_ev, tag_evs, tool_calls):
    p1 = phase1_by_agent.get(aid)
    claim = phase2_by_agent.get(aid)
    is_winner = aid == winner_id
    return AgentDetail(
        agent_id=aid,
        role="winner" if is_winner else "candidate",
        passed=p1.passed if p1 is not None else False,
        fit_score=p1.fit_score if p1 is not None else 0.0,
        claim_decision=claim.decision if claim is not None else None,
        justification=claim.justification if claim is not None else None,
        output_summary=executed.output_summary if (is_winner and executed is not None) else None,
        output_content=executed.output_content if (is_winner and executed is not None) else None,
        llm_metadata=executed.llm_metadata if (is_winner and executed is not None) else None,
        elo_deltas=dict(elo_ev.deltas) if (is_winner and elo_ev is not None) else {},
        tags_acquired=[TagAcquiredInfo(tag=t.tag, initial_elo=t.initial_elo) for t in tag_evs] if is_winner else [],
        tool_calls=[ToolCallInfo(tool_name=t.tool_name, arguments=t.arguments, result=t.result, latency_ms=t.latency_ms) for t in tool_calls] if is_winner else [],
    )


def _tool_groups(tool_evs: list[ToolCalledEvent]) -> list[list[ToolCalledEvent]]:
    """Run-length encoding par tool_name : appels consécutifs du même tool fusionnés."""
    groups: list[list[ToolCalledEvent]] = []
    for t in tool_evs:
        if groups and groups[-1][-1].tool_name == t.tool_name:
            groups[-1].append(t)
        else:
            groups.append([t])
    return groups


class _SubTaskRun:
    """Events d'une sous-tâche (ou de l'unique tâche d'un run simple), dans l'ordre."""
    def __init__(self, task_id: str, events: list[ClaimEvent]):
        self.task_id = task_id
        self.phase1 = [e for e in events if isinstance(e, Phase1FilteredEvent)]
        self.phase2 = {e.agent_id: e for e in events if isinstance(e, Phase2ClaimedEvent)}
        self.phase1_by_agent = {e.agent_id: e for e in self.phase1}
        self.dispatched = next((e for e in events if isinstance(e, DispatchedEvent)), None)
        self.unassigned = next((e for e in events if isinstance(e, UnassignedEvent)), None)
        self.executed = next((e for e in events if isinstance(e, ExecutedEvent)), None)
        self.qa = next((e for e in events if isinstance(e, QAEvaluatedEvent)), None)
        self.elo = next((e for e in events if isinstance(e, EloUpdatedEvent)), None)
        self.tags = [e for e in events if isinstance(e, TagAcquiredEvent)]
        self.tools = [e for e in events if isinstance(e, ToolCalledEvent)]

    @property
    def winner_id(self) -> str | None:
        return self.dispatched.agent_id if self.dispatched is not None else None

    @property
    def outcome(self) -> Outcome:
        if self.unassigned is not None or self.dispatched is None:
            return "unassigned"
        if self.qa is None:
            return "no_qa"
        return "qa_pass" if self.qa.success else "qa_fail"


def _split_sub_runs(events: list[ClaimEvent]) -> list[_SubTaskRun]:
    """Découpe les events (hors task_divided/task_aggregated) en runs de sous-tâche.

    Un nouveau run démarre à un Phase1FilteredEvent qui suit un event non-Phase1.
    Gère le run simple (1 run) et le run divisé (N sous-tâches contiguës).
    """
    runs: list[list[ClaimEvent]] = []
    current: list[ClaimEvent] = []
    for e in events:
        if isinstance(e, (TaskDividedEvent, TaskAggregatedEvent)):
            continue
        if isinstance(e, Phase1FilteredEvent) and current and not isinstance(current[-1], Phase1FilteredEvent):
            runs.append(current)
            current = []
        current.append(e)
    if current:
        runs.append(current)
    return [_SubTaskRun(r[0].task_id, r) for r in runs if r]


class _EdgeAccumulator:
    def __init__(self):
        self.backbone: list[GraphEdge] = []
        self._seen: set[tuple[str, str]] = set()

    def add_backbone(self, frm: str, to: str) -> None:
        if (frm, to) not in self._seen:
            self._seen.add((frm, to))
            self.backbone.append(GraphEdge(from_node=frm, to=to))

    def snapshot(self, fanout: list[tuple[str, str]]) -> list[GraphEdge]:
        return list(self.backbone) + [GraphEdge(from_node=f, to=t) for f, t in fanout]


def _evaluator_detail(run: "_SubTaskRun") -> EvaluatorDetail:
    if run is None or run.qa is None:
        return EvaluatorDetail(ran=False, success=None, score=None, reason=None)
    return EvaluatorDetail(
        ran=True, success=run.qa.success, score=run.qa.score, reason=run.qa.reason,
        criteria_results=dict(run.qa.criteria_results), judge=run.qa.judge, spec=run.qa.spec,
    )


def _dispatch_detail(run: "_SubTaskRun") -> DispatchDetail:
    return DispatchDetail(
        candidates=[CandidateInfo(agent_id=e.agent_id, passed=e.passed, fit_score=e.fit_score) for e in run.phase1],
        claims=[ClaimInfo(agent_id=e.agent_id, decision=e.decision, justification=e.justification) for e in run.phase2.values()],
        winner_agent_id=run.winner_id,
        dispatch_reason=run.dispatched.reason if run.dispatched is not None else None,
        unassigned_reason=run.unassigned.reason if run.unassigned is not None else None,
    )


def _scope_detail(input_detail: InputDetail, run: "_SubTaskRun | None") -> StepDetail:
    """StepDetail scopé sur une sous-tâche (réutilisé par chaque jalon de cette sous-tâche)."""
    detail = StepDetail(input=input_detail)
    if run is None:
        return detail
    detail.dispatch = _dispatch_detail(run)
    detail.evaluator = _evaluator_detail(run)
    detail.testset = TestSetDetail(forked=(run.outcome == "qa_fail"), from_task_id=run.task_id)
    winner = run.winner_id
    winner_tools = [t for t in run.tools if t.agent_id == winner] if winner else []
    for aid in run.phase1_by_agent:
        detail.agents[aid] = _agent_detail(
            aid, run.phase1_by_agent, run.phase2, winner, run.executed, run.elo, run.tags, winner_tools
        )
    if run.executed is not None:
        detail.output = OutputDetail(
            produced=True, output_summary=run.executed.output_summary,
            output_content=run.executed.output_content, llm_metadata=run.executed.llm_metadata,
        )
    return detail


def _milestones_simple(run: "_SubTaskRun | None", record: SessionTaskRecord | None, tid: str) -> list[GraphStep]:
    input_detail = _make_input_detail(record, tid)
    detail = _scope_detail(input_detail, run)
    acc = _EdgeAccumulator()
    steps: list[GraphStep] = []

    # INPUT
    steps.append(GraphStep(milestone_type="input", label="INPUT", active_nodes=["input"],
                           active_edges=acc.snapshot([]), outcome="no_qa", detail=detail,
                           todo=_todo_simple(record, tid, "input", run)))
    if run is None:
        return steps

    winner = run.winner_id
    # DISPATCH
    acc.add_backbone("input", "dispatch")
    fan = [("dispatch", winner)] if winner else []
    nodes_active = ["dispatch"] + ([winner] if winner else [])
    steps.append(GraphStep(milestone_type="dispatch", label="DISPATCH", sub_task_id=tid,
                           active_nodes=nodes_active, active_edges=acc.snapshot(fan),
                           winner_agent_id=winner, outcome=run.outcome, detail=detail,
                           todo=_todo_simple(record, tid, "dispatch", run)))
    if winner is None:
        return steps  # unassigned : la séquence s'arrête au dispatch

    # TOOL milestones (Task 4 les ajoute) ; le caller assigne le todo
    for ts in _tool_milestones(run, detail, acc, tid):
        ts.todo = _todo_simple(record, tid, "tool", run)
        steps.append(ts)

    # AGENT (executed)
    steps.append(GraphStep(milestone_type="agent", label=f"AGENT · {winner}", sub_task_id=tid,
                           active_nodes=[winner], active_edges=acc.snapshot([("dispatch", winner)]),
                           winner_agent_id=winner, outcome=run.outcome, detail=detail,
                           todo=_todo_simple(record, tid, "agent", run)))

    # EVALUATOR
    if run.qa is not None:
        fanq = [("dispatch", winner), (winner, "evaluator")]
        nodes_q = ["evaluator"]
        if run.outcome == "qa_fail":
            fanq.append(("evaluator", "testset"))
            nodes_q.append("testset")
        steps.append(GraphStep(milestone_type="evaluator", label="EVALUATOR", sub_task_id=tid,
                               active_nodes=nodes_q, active_edges=acc.snapshot(fanq),
                               winner_agent_id=winner, outcome=run.outcome, detail=detail,
                               todo=_todo_simple(record, tid, "evaluator", run)))

    # OUTPUT
    if run.outcome != "qa_fail":
        acc.add_backbone("evaluator", "output")
        steps.append(GraphStep(milestone_type="output", label="OUTPUT", active_nodes=["output"],
                               active_edges=acc.snapshot([]), winner_agent_id=winner, outcome=run.outcome,
                               detail=detail, todo=_todo_simple(record, tid, "output", run)))
    return steps


def _tool_milestones(run, detail, acc, tid):  # remplacé en Task 4
    return []


def _todo_simple(record, tid, milestone, run):  # remplacé en Task 6
    return []


def _milestones_divided(divided_ev, aggregated_ev, sub_runs, parent_record, parent_id):  # remplacé en Task 5
    return []


def _sub_desc(divided_ev, task_id):  # remplacé en Task 5
    return task_id


def _todo_divided(divided_ev, sub_runs, milestone, current_task_id):  # remplacé en Task 5/6
    return []


def build_graph(events: list[ClaimEvent], session_meta: SessionMeta | None = None) -> GraphModel:
    nodes = _build_nodes(events)
    edges = _build_edges(nodes, events)

    divided_ev = next((e for e in events if isinstance(e, TaskDividedEvent)), None)
    aggregated_ev = next((e for e in events if isinstance(e, TaskAggregatedEvent)), None)
    sub_runs = _split_sub_runs(events)

    if divided_ev is not None:
        parent_id = divided_ev.task_id
        parent_record = _meta_record(session_meta, parent_id)
        steps = _milestones_divided(divided_ev, aggregated_ev, sub_runs, parent_record, parent_id)
    else:
        run = sub_runs[0] if sub_runs else None
        tid = run.task_id if run is not None else (session_meta.tasks[0].id if session_meta and session_meta.tasks else "task")
        record = _meta_record(session_meta, tid)
        steps = _milestones_simple(run, record, tid)

    return GraphModel(nodes=nodes, edges=edges, steps=steps)
