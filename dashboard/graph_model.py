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
    required_tags: dict[str, int] = Field(default_factory=dict)


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
    # récit progressif : nb de sous-tâches validées collectées à l'instant T (< total tant que
    # l'agrégation finale n'a pas eu lieu). collected == total au jalon aggregator/output.
    collected: int = 0
    total: int = 0


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


def _has_qa_fail(events: list[ClaimEvent]) -> bool:
    return any(isinstance(e, QAEvaluatedEvent) and not e.success for e in events)


def _build_nodes(events: list[ClaimEvent]) -> list[GraphNode]:
    nodes = [
        GraphNode(id="input", layer="top", type="input", label="Input"),
        GraphNode(id="dispatch", layer="center", type="dispatch", label="Dispatch"),
        GraphNode(id="evaluator", layer="center", type="evaluator", label="Evaluator"),
        GraphNode(id="output", layer="top", type="output", label="Output"),
    ]
    # testset (fork de régression) n'a de sens qu'en cas d'échec QA — sinon nœud flottant sans arête.
    if _has_qa_fail(events):
        nodes.append(GraphNode(id="testset", layer="top", type="testset", label="TestSet"))
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
    """Arêtes statiques = la pipeline réelle (mêmes arêtes que le backbone/fan-out des jalons).

    Simple : input→dispatch→agents→evaluator→output.
    Divisé : input→divider→dispatch→agents→evaluator→aggregator→output.
    Tools en canopée (agent→tool). testset (fork) seulement sur échec QA.
    """
    agent_ids = [n.id for n in nodes if n.type == "agent"]
    divided = any(n.id == "divider" for n in nodes)
    edges: list[GraphEdge] = []
    if divided:
        edges.append(GraphEdge(from_node="input", to="divider"))
        edges.append(GraphEdge(from_node="divider", to="dispatch"))
    else:
        edges.append(GraphEdge(from_node="input", to="dispatch"))
    edges += [GraphEdge(from_node="dispatch", to=aid) for aid in agent_ids]
    edges += [GraphEdge(from_node=aid, to="evaluator") for aid in agent_ids]
    for aid, tname in _distinct_tools(events):
        edges.append(GraphEdge(from_node=aid, to=_tool_node_id(tname)))
    if divided:
        edges.append(GraphEdge(from_node="evaluator", to="aggregator"))
        edges.append(GraphEdge(from_node="aggregator", to="output"))
    else:
        edges.append(GraphEdge(from_node="evaluator", to="output"))
    if _has_qa_fail(events):
        edges.append(GraphEdge(from_node="evaluator", to="testset"))
    return edges


def _meta_record(session_meta: SessionMeta | None, task_id: str) -> SessionTaskRecord | None:
    if session_meta is None:
        return None
    for rec in session_meta.tasks:
        if rec.id == task_id:
            return rec
    return None


def _make_input_detail(meta_record: SessionTaskRecord | None, task_id: str) -> InputDetail:
    if meta_record is not None:
        return InputDetail(
            task_id=task_id, description=meta_record.description,
            required_tags=dict(meta_record.required_tags), context=meta_record.context,
        )
    return InputDetail(task_id=task_id, description=task_id)


def _agent_detail(
    aid: str,
    phase1_by_agent: dict[str, Phase1FilteredEvent],
    phase2_by_agent: dict[str, Phase2ClaimedEvent],
    winner_id: str | None,
    executed: ExecutedEvent | None,
    elo_ev: EloUpdatedEvent | None,
    tag_evs: list[TagAcquiredEvent],
    tool_calls: list[ToolCalledEvent],
) -> AgentDetail:
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


def _tool_milestones(run: "_SubTaskRun", input_detail_owner: StepDetail, acc: _EdgeAccumulator, tid: str) -> list[GraphStep]:
    winner = run.winner_id
    if winner is None:
        return []
    winner_tools = [t for t in run.tools if t.agent_id == winner]
    steps: list[GraphStep] = []
    for group in _tool_groups(winner_tools):
        tname = group[0].tool_name
        tool_node = _tool_node_id(tname)
        # detail scopé tool pour ce jalon (réutilise le StepDetail de la sous-tâche, surcharge .tool).
        # Copie superficielle volontaire : `.tool` est le seul champ qui diverge par jalon.
        # NE PAS muter detail.agents / detail.dispatch / detail.evaluator après ce point
        # (objets partagés entre jalons frères → mutation corromprait les voisins).
        detail = input_detail_owner.model_copy()
        detail.tool = ToolDetail(
            agent_id=winner, tool_name=tname,
            calls=[ToolCallInfo(tool_name=c.tool_name, arguments=c.arguments, result=c.result, latency_ms=c.latency_ms) for c in group],
        )
        fan = [("dispatch", winner), (winner, tool_node)]
        label = f"TOOL · {tname}" + (f" ×{len(group)}" if len(group) > 1 else "")
        steps.append(GraphStep(milestone_type="tool", label=label, sub_task_id=tid,
                               active_nodes=[winner, tool_node], active_edges=acc.snapshot(fan),
                               winner_agent_id=winner, outcome=run.outcome, detail=detail,
                               todo=[]))   # le caller assigne le todo
    return steps


def _root_state(milestone: str) -> Literal["current", "done"]:
    return "done" if milestone == "output" else "current"


def _todo_simple(record, tid, milestone, run) -> list[TodoItem]:
    desc = record.description if record is not None else tid
    if run is not None and milestone == "evaluator" and run.outcome == "qa_fail":
        state: Literal["pending", "current", "done", "failed"] = "failed"
    else:
        state = _root_state(milestone)
    return [TodoItem(id=tid, description=desc, state=state, is_root=True)]


def _milestones_divided(divided_ev, aggregated_ev, sub_runs, parent_record, parent_id) -> list[GraphStep]:
    parent_input = _make_input_detail(parent_record, parent_id)
    parent_desc = parent_input.description
    acc = _EdgeAccumulator()
    steps: list[GraphStep] = []

    def td(milestone, current_task_id):
        return _todo_divided(divided_ev, sub_runs, milestone, current_task_id, parent_desc)

    # INPUT (parent)
    parent_detail = StepDetail(input=parent_input)
    steps.append(GraphStep(milestone_type="input", label="INPUT", active_nodes=["input"],
                           active_edges=acc.snapshot([]), outcome="divided", detail=parent_detail,
                           todo=td("input", None)))

    # DIVIDER
    acc.add_backbone("input", "divider")
    div_detail = StepDetail(input=parent_input, divider=DividerDetail(
        divided=True,
        sub_tasks=[DividerSubTaskInfo(id=st.id, description=st.description, depends_on=list(st.depends_on), required_tags=dict(getattr(st, "required_tags", {}) or {})) for st in divided_ev.sub_tasks],
    ))
    steps.append(GraphStep(milestone_type="divider", label="DIVIDER", active_nodes=["divider"],
                           active_edges=acc.snapshot([]), outcome="divided", detail=div_detail,
                           todo=td("divider", None)))

    # Récit progressif de collecte : l'aggregator s'allume à chaque sous-tâche validée.
    total = len(sub_runs)
    collected = 0

    # Sous-tâches dans l'ordre d'émission (= ordre topologique de run_chain)
    for idx, run in enumerate(sub_runs):
        sub_input = InputDetail(task_id=run.task_id, description=_sub_desc(divided_ev, run.task_id),
                                required_tags=_sub_tags(divided_ev, run.task_id))
        detail = _scope_detail(sub_input, run)
        winner = run.winner_id

        acc.add_backbone("divider", "dispatch")
        fan = [("dispatch", winner)] if winner else []
        nodes_active = ["dispatch"] + ([winner] if winner else [])
        steps.append(GraphStep(milestone_type="dispatch", label=f"DISPATCH · {idx + 1}", sub_task_id=run.task_id,
                               order_index=idx, active_nodes=nodes_active, active_edges=acc.snapshot(fan),
                               winner_agent_id=winner, outcome=run.outcome, detail=detail,
                               todo=td("dispatch", run.task_id)))
        if winner is None:
            continue

        for ts in _tool_milestones(run, detail, acc, run.task_id):
            ts.order_index = idx
            ts.todo = td("tool", run.task_id)
            steps.append(ts)

        steps.append(GraphStep(milestone_type="agent", label=f"AGENT · {winner}", sub_task_id=run.task_id,
                               order_index=idx, active_nodes=[winner], active_edges=acc.snapshot([("dispatch", winner)]),
                               winner_agent_id=winner, outcome=run.outcome, detail=detail,
                               todo=td("agent", run.task_id)))

        if run.qa is not None:
            fanq = [("dispatch", winner), (winner, "evaluator")]
            nodes_q = ["evaluator"]
            ev_detail = detail
            if run.outcome == "qa_fail":
                fanq.append(("evaluator", "testset"))
                nodes_q.append("testset")
            elif run.outcome == "qa_pass":
                # sortie validée → collectée par l'aggregator (qui s'allume, arête transitoire).
                # shallow copy : on surcharge .aggregator sans muter le detail partagé des frères.
                collected += 1
                nodes_q.append("aggregator")
                fanq.append(("evaluator", "aggregator"))
                ev_detail = detail.model_copy()
                ev_detail.aggregator = AggregatorDetail(aggregated=False, collected=collected, total=total)
            steps.append(GraphStep(milestone_type="evaluator", label=f"EVALUATOR · {idx + 1}", sub_task_id=run.task_id,
                                   order_index=idx, active_nodes=nodes_q, active_edges=acc.snapshot(fanq),
                                   winner_agent_id=winner, outcome=run.outcome, detail=ev_detail,
                                   todo=td("evaluator", run.task_id)))

    # AGGREGATOR
    if aggregated_ev is not None:
        acc.add_backbone("evaluator", "aggregator")
        agg_detail = StepDetail(input=parent_input, aggregator=AggregatorDetail(
            aggregated=True, sub_task_ids=list(aggregated_ev.sub_task_ids),
            output_summary=aggregated_ev.output_summary, output_content=aggregated_ev.output_content,
            collected=collected, total=total,
        ))
        agg_detail.output = OutputDetail(produced=True, output_summary=aggregated_ev.output_summary,
                                         output_content=aggregated_ev.output_content, llm_metadata=aggregated_ev.llm_metadata)
        steps.append(GraphStep(milestone_type="aggregator", label="AGGREGATOR", active_nodes=["aggregator"],
                               active_edges=acc.snapshot([]), outcome="divided", detail=agg_detail,
                               todo=td("aggregator", None)))

        # OUTPUT — l'aggregator reste allumé (l'output est produit PAR lui : sinon une arête
        # ember pointe depuis un nœud éteint, incohérent comme état terminal).
        acc.add_backbone("aggregator", "output")
        steps.append(GraphStep(milestone_type="output", label="OUTPUT", active_nodes=["aggregator", "output"],
                               active_edges=acc.snapshot([]), outcome="divided", detail=agg_detail,
                               todo=td("output", None)))
    return steps


def _sub_desc(divided_ev, task_id: str) -> str:
    for st in divided_ev.sub_tasks:
        if st.id == task_id:
            return st.description
    return task_id


def _sub_tags(divided_ev, task_id: str) -> dict[str, int]:
    for st in divided_ev.sub_tasks:
        if st.id == task_id:
            return dict(getattr(st, "required_tags", {}) or {})
    return {}


def _todo_divided(divided_ev, sub_runs, milestone, current_task_id, root_desc="(input)") -> list[TodoItem]:
    # racine : description réelle de la tâche parent (pas un placeholder)
    items = [TodoItem(id=divided_ev.task_id, description=root_desc, state=_root_state(milestone), is_root=True)]
    if milestone == "input":
        return items
    # ordre des sous-tâches = ordre d'exécution (sub_runs), fallback ordre divider
    order = [r.task_id for r in sub_runs] or [st.id for st in divided_ev.sub_tasks]
    run_by_id = {r.task_id: r for r in sub_runs}
    # index de la sous-tâche courante dans l'ordre d'exécution (None si jalon parent)
    cur_idx = order.index(current_task_id) if current_task_id in order else None
    desc_by_id = {st.id: st.description for st in divided_ev.sub_tasks}
    for i, tid in enumerate(order):
        run = run_by_id.get(tid)
        if milestone in ("aggregator", "output"):
            state = ("failed" if (run is not None and run.outcome == "qa_fail") else "done")
        elif cur_idx is None:
            state = "pending"  # jalon divider : tout pending
        elif i < cur_idx:
            state = ("failed" if (run is not None and run.outcome == "qa_fail") else "done")
        elif i == cur_idx:
            # current jusqu'à son evaluator résolu
            if milestone == "evaluator" and run is not None and run.outcome == "qa_fail":
                state = "failed"
            elif milestone == "evaluator" and run is not None and run.outcome == "qa_pass":
                state = "done"
            else:
                state = "current"
        else:
            state = "pending"
        items.append(TodoItem(id=tid, description=desc_by_id.get(tid, tid), state=state, is_root=False))
    return items


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
