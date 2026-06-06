from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from aaosa.qa.judge import JudgeBreakdown
from aaosa.qa.spec import EvaluatorSpec
from aaosa.schemas.output import LLMMetadata
from aaosa.tracing.events import (
    ClaimEvent,
    DiagnosedEvent,
    DispatchedEvent,
    EloUpdatedEvent,
    ExecutedEvent,
    Phase1FilteredEvent,
    Phase2ClaimedEvent,
    QAEvaluatedEvent,
    RosterGapEvent,
    TagAcquiredEvent,
    TaskAggregatedEvent,
    TaskDividedEvent,
    ToolCalledEvent,
    UnassignedEvent,
)
from aaosa.tracing.store import SessionMeta, SessionTaskRecord

NodeLayer = Literal["tools", "bottom", "center", "top"]          # conservé pour l'API ; le layout frontend n'en dépend plus
NodeType = Literal["input", "tagger", "dispatch", "evaluator", "diagnostic", "roster_gap",
                   "output", "testset", "agent", "divider", "aggregator", "tool"]
MilestoneType = Literal["input", "tagger", "divider", "dispatch", "agent", "tool",
                        "evaluator", "diagnostic", "roster_gap", "aggregator", "output"]
Outcome = Literal["qa_pass", "qa_fail", "unassigned", "no_qa", "divided", "roster_gap", "diagnosed"]
EdgeFlow = Literal["ascent", "descent", "transient"]


class GraphNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    layer: NodeLayer
    type: NodeType
    label: str
    task_id: str | None = None   # appartenance de branche (None pour input/tagger/output)
    agent_id: str | None = None  # nœud agent : agent_id réel (badge ×N côté frontend)


class GraphEdge(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    from_node: str = Field(alias="from")
    to: str
    flow: EdgeFlow = "ascent"


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


class DiagnosticDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attribution: Literal["agent", "evaluator", "task_spec", "unattributed"]
    reason: str
    consignes: str | None = None
    route_taken: Literal["agent", "evaluator", "task_spec", "stop"]   # stop = unattributed


class RosterGapDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    missing_tags: list[str] = Field(default_factory=list)


class DividerDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    divided: bool
    sub_tasks: list[DividerSubTaskInfo] = Field(default_factory=list)
    origin: Literal["recovery", "diagnostic"] = "recovery"   # D1 (unassigned) vs D3 (task_spec)


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
    diagnostic: DiagnosticDetail | None = None
    roster_gap: RosterGapDetail | None = None

    @classmethod
    def empty(cls, task_id: str, description: str) -> "StepDetail":
        return cls(input=InputDetail(task_id=task_id, description=description))


class TodoItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    description: str
    state: Literal["pending", "current", "done", "failed"]
    is_root: bool
    parent_id: str | None = None
    depth: int = 0
    first_step_index: int | None = None   # point de navigation timeline (calcul backend)
    note: str | None = None               # annotation de marge : "pass 2", "roster gap", "route X"


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
    pass_index: int = 0   # 0 = première tentative, 1 = passe retry (D3)


class TaskBranch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    parent_id: str | None = None
    depth: int = 0
    order_index: int = 0
    description: str = ""


class GraphModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    steps: list[GraphStep]
    tasks: list[TaskBranch] = Field(default_factory=list)   # topologie de l'arbre (layout frontend)


def _nid(kind: str, tid: str, extra: str | None = None) -> str:
    return f"{kind}:{tid}" + (f":{extra}" if extra else "")


def _has_result(tid: str, runs: dict[str, "_TaskRun"]) -> bool:
    """La tâche a un résultat exploitable, à plat ou via son sous-arbre (récursif)."""
    run = runs.get(tid)
    if run is None:
        return False
    if run.aggregated is not None:
        return True
    if run.divided is not None:
        sinks = _sink_ids(run.divided, runs)
        return bool(sinks) and _has_result(sinks[-1], runs)
    return run.succeeded


def _sink_ids(divided_ev: TaskDividedEvent, runs: dict[str, "_TaskRun"]) -> list[str]:
    """Même règle que le runtime `_sinks` : un réussi non consommé par un réussi.
    Réussi = _has_result (couvre les sous-tâches elles-mêmes divisées)."""
    ok = {st.id for st in divided_ev.sub_tasks if _has_result(st.id, runs)}
    consumed = {dep for st in divided_ev.sub_tasks if st.id in ok
                for dep in st.depends_on if dep in ok}
    return [st.id for st in divided_ev.sub_tasks if st.id in ok and st.id not in consumed]


def _exit_node(tid: str, runs: dict[str, "_TaskRun"]) -> str | None:
    """Nœud qui porte le résultat final de la tâche (départ de sa descente).
    Court-circuit single-sink (D2) : l'exit du sous-arbre est l'exit du sink —
    la descente saute le niveau (aucun aggregator au court-circuit)."""
    run = runs.get(tid)
    if run is None:
        return None
    if run.aggregated is not None:
        return _nid("aggregator", tid)
    if run.divided is not None:
        sinks = _sink_ids(run.divided, runs)
        return _exit_node(sinks[-1], runs) if sinks else None
    if not run.succeeded:
        return None
    last = run.passes[-1]
    if last.qa is not None or run.reeval is not None:
        return _nid("evaluator", tid)
    if last.winner_id:
        return _nid("agent", tid, last.winner_id)
    return None


def _division_origin(run: "_TaskRun") -> Literal["recovery", "diagnostic"]:
    if run.diagnosed is not None and run.diagnosed.attribution == "task_spec":
        return "diagnostic"
    return "recovery"


def _divider_anchor(run: "_TaskRun", tid: str) -> str | None:
    """D'où monte l'arête vers divider:<tid> : DIAG (D3) ou le dispatch raté (D1)."""
    if _division_origin(run) == "diagnostic":
        return _nid("diagnostic", tid)
    if run.passes:
        return _nid("dispatch", tid)
    return None


def _winners(run: "_TaskRun") -> list[str]:
    """Winners distincts à travers les passes (ordre d'apparition)."""
    seen: list[str] = []
    for p in run.passes:
        w = p.winner_id
        if w and w not in seen:
            seen.append(w)
    return seen


def _branch_tools(run: "_TaskRun") -> list[tuple[str, str]]:
    """(winner, tool_name) distincts du/des winner(s), ordre d'apparition."""
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for p in run.passes:
        w = p.winner_id
        if not w:
            continue
        for t in p.tools:
            if t.agent_id == w and (w, t.tool_name) not in seen:
                seen.add((w, t.tool_name))
                out.append((w, t.tool_name))
    return out


def _build_structure(
    tree: "_Tree", runs: dict[str, "_TaskRun"], root_tags: dict[str, int],
) -> tuple[list[GraphNode], list[GraphEdge]]:
    nodes: list[GraphNode] = [GraphNode(id="input", layer="top", type="input", label="Input")]
    edges: list[GraphEdge] = []
    seen_edges: set[tuple[str, str]] = set()

    def add_edge(frm: str | None, to: str | None, flow: EdgeFlow) -> None:
        if frm and to and (frm, to) not in seen_edges:
            seen_edges.add((frm, to))
            edges.append(GraphEdge(from_node=frm, to=to, flow=flow))

    has_tagger = bool(root_tags)
    if has_tagger:
        nodes.append(GraphNode(id="tagger", layer="top", type="tagger", label="Tagger"))
        add_edge("input", "tagger", "ascent")
    nodes.append(GraphNode(id="output", layer="top", type="output", label="Output"))
    trunk_anchor = "tagger" if has_tagger else "input"

    def visit(tid: str, entry_anchor: str) -> None:
        run = runs.get(tid)
        if run is None:
            return   # tâche jamais tracée (dep sautée) : pas de nœuds
        if run.roster_gap is not None:
            gid = _nid("roster_gap", tid)
            nodes.append(GraphNode(id=gid, layer="center", type="roster_gap",
                                   label="GAP · " + " ".join(run.roster_gap.missing_tags),
                                   task_id=tid))
            add_edge(entry_anchor, gid, "ascent")
            return   # cul-de-sac : aucune descente
        if run.passes:
            did = _nid("dispatch", tid)
            nodes.append(GraphNode(id=did, layer="center", type="dispatch", label="DISPATCH", task_id=tid))
            add_edge(entry_anchor, did, "ascent")
            has_eval = any(p.qa is not None for p in run.passes) or run.reeval is not None
            if has_eval:
                nodes.append(GraphNode(id=_nid("evaluator", tid), layer="center",
                                       type="evaluator", label="EVAL", task_id=tid))
            for w in _winners(run):
                aid = _nid("agent", tid, w)
                nodes.append(GraphNode(id=aid, layer="bottom", type="agent", label=w,
                                       task_id=tid, agent_id=w))
                add_edge(did, aid, "ascent")
                if has_eval:
                    add_edge(aid, _nid("evaluator", tid), "descent")
            for w, tname in _branch_tools(run):
                tnid = _nid("tool", tid, tname)
                nodes.append(GraphNode(id=tnid, layer="tools", type="tool", label=tname, task_id=tid))
                add_edge(_nid("agent", tid, w), tnid, "transient")
        if run.diagnosed is not None and run.passes:  # garde : pas de DIAG sans passe (trace partielle)
            dgid = _nid("diagnostic", tid)
            nodes.append(GraphNode(id=dgid, layer="center", type="diagnostic", label="DIAG", task_id=tid))
            add_edge(_nid("evaluator", tid), dgid, "descent")
            att = run.diagnosed.attribution
            if att == "agent" and len(run.passes) > 1:
                add_edge(dgid, _nid("dispatch", tid), "transient")          # loop-back retry
            elif att == "evaluator":
                add_edge(dgid, _nid("evaluator", tid), "transient")         # EVAL rallumé (v2)
                if len(run.passes) > 1:
                    add_edge(dgid, _nid("dispatch", tid), "transient")      # ré-éval KO → retry
        if run.divided is not None:
            dvid = _nid("divider", tid)
            nodes.append(GraphNode(id=dvid, layer="center", type="divider", label="DIVIDER", task_id=tid))
            add_edge(_divider_anchor(run, tid) or entry_anchor, dvid, "ascent")
            for st in run.divided.sub_tasks:
                visit(st.id, dvid)
            # deps inter-sœurs réussies : exit(dep) → dispatch(consommateur), transient
            for st in run.divided.sub_tasks:
                consumer = runs.get(st.id)
                if consumer is None or not consumer.passes:
                    continue
                for dep in st.depends_on:
                    if _has_result(dep, runs):
                        add_edge(_exit_node(dep, runs), _nid("dispatch", st.id), "transient")
            if run.aggregated is not None:
                agid = _nid("aggregator", tid)
                nodes.append(GraphNode(id=agid, layer="center", type="aggregator",
                                       label="AGGREGATOR", task_id=tid))
                for s in _sink_ids(run.divided, runs):
                    add_edge(_exit_node(s, runs), agid, "descent")

    visit(tree.root_id, trunk_anchor)
    final_exit = _exit_node(tree.root_id, runs)
    if final_exit:
        add_edge(final_exit, "output", "descent")
    return nodes, edges


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


class _Pass:
    """Une tentative complète (Phase1 → … → QA) d'une tâche. Corps = ex-_SubTaskRun."""
    def __init__(self, events: list[ClaimEvent]):
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
        # task_id backfilled by _TaskRun after construction (bridges to old milestones code)
        self.task_id: str = ""

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


class _TaskRun:
    """Toutes les traces d'une tâche : passes (retry D3 inclus), diagnostic, ré-éval,
    division, agrégation, roster gap."""
    def __init__(self, task_id: str, events: list[ClaimEvent]):
        self.task_id = task_id
        self.divided = next((e for e in events if isinstance(e, TaskDividedEvent)), None)
        self.aggregated = next((e for e in events if isinstance(e, TaskAggregatedEvent)), None)
        self.roster_gap = next((e for e in events if isinstance(e, RosterGapEvent)), None)
        self.diagnosed: DiagnosedEvent | None = None
        self.reeval: QAEvaluatedEvent | None = None
        self.passes: list[_Pass] = []
        self._split_passes(events)

    def _split_passes(self, events: list[ClaimEvent]) -> None:
        current: list[ClaimEvent] = []
        retry_started = False
        for e in events:
            if isinstance(e, (TaskDividedEvent, TaskAggregatedEvent, RosterGapEvent)):
                continue
            if isinstance(e, DiagnosedEvent):
                self.diagnosed = e
                continue
            if self.diagnosed is not None and not retry_started:
                if isinstance(e, Phase1FilteredEvent):
                    retry_started = True
                    if current:
                        p = _Pass(current)
                        p.task_id = self.task_id
                        self.passes.append(p)
                    current = [e]
                    continue
                if isinstance(e, QAEvaluatedEvent):
                    self.reeval = e   # ré-éval v2 (route evaluator) : QA post-diag sans nouveau Phase1
                    continue
            current.append(e)
        if current:
            p = _Pass(current)
            p.task_id = self.task_id
            self.passes.append(p)

    @property
    def succeeded(self) -> bool:
        """La tâche a produit un résultat exploitable À PLAT (hors division)."""
        if self.reeval is not None and self.reeval.success:
            return True
        if not self.passes:
            return False
        last = self.passes[-1]
        if last.executed is None:
            return False
        return last.outcome in ("qa_pass", "no_qa")


def _parse_runs(events: list[ClaimEvent]) -> dict[str, _TaskRun]:
    """Partition par task_id (ordre de première apparition), un _TaskRun par tâche."""
    by_task: dict[str, list[ClaimEvent]] = {}
    for e in events:
        by_task.setdefault(e.task_id, []).append(e)
    return {tid: _TaskRun(tid, evs) for tid, evs in by_task.items()}


class _Tree:
    """Arbre de tâches reconstruit depuis TOUS les TaskDividedEvent."""
    def __init__(self, root_id: str, children: dict[str, list[str]],
                 parents: dict[str, str], descriptions: dict[str, str],
                 tags: dict[str, dict[str, int]],
                 first_idx: dict[str, int]):
        self.root_id = root_id
        self._children = children
        self._parents = parents
        self._descriptions = descriptions
        self._tags = tags
        self._first_idx = first_idx

    def children(self, tid: str) -> list[str]:
        # ordre d'exécution réel (premier event), fallback ordre du divider
        kids = self._children.get(tid, [])
        return sorted(kids, key=lambda c: self._first_idx.get(c, 10**9))

    def parent(self, tid: str) -> str | None:
        return self._parents.get(tid)

    def depth(self, tid: str) -> int:
        d, cur = 0, tid
        while (p := self._parents.get(cur)) is not None:
            d, cur = d + 1, p
        return d

    def description(self, tid: str) -> str:
        return self._descriptions.get(tid, tid)

    def tags(self, tid: str) -> dict[str, int]:
        return dict(self._tags.get(tid, {}))

    def walk_ids(self) -> list[str]:
        """DFS préordre depuis la racine (ordre d'exécution)."""
        out: list[str] = []
        def rec(tid: str) -> None:
            out.append(tid)
            for c in self.children(tid):
                rec(c)
        rec(self.root_id)
        return out


def _build_tree(events: list[ClaimEvent], session_meta: SessionMeta | None) -> _Tree:
    children: dict[str, list[str]] = {}
    parents: dict[str, str] = {}
    descriptions: dict[str, str] = {}
    tags: dict[str, dict[str, int]] = {}
    first_idx: dict[str, int] = {}
    for i, e in enumerate(events):
        first_idx.setdefault(e.task_id, i)
        if isinstance(e, TaskDividedEvent):
            children[e.task_id] = [st.id for st in e.sub_tasks]
            for st in e.sub_tasks:
                parents[st.id] = e.task_id
                descriptions[st.id] = st.description
                tags[st.id] = dict(st.required_tags)

    if session_meta is not None and session_meta.tasks:
        root_id = session_meta.tasks[0].id
        # Meta désynchronisé (run_recovery crée sa propre Task interne) : si l'id du meta
        # n'apparaît jamais dans la trace, la racine réelle = première tâche non-enfant.
        # Description/tags du meta sont reportés dessus (même tâche sémantique).
        # Trace vide : on garde la racine du meta (INPUT seul, pas de crash).
        if root_id not in first_idx:
            fallback = next((tid for tid in first_idx if tid not in parents), None)
            if fallback is not None:
                root_id = fallback
        descriptions[root_id] = session_meta.tasks[0].description
        tags[root_id] = dict(session_meta.tasks[0].required_tags)
    else:
        root_id = next((tid for tid in first_idx if tid not in parents), "task")
    return _Tree(root_id, children, parents, descriptions, tags, first_idx)


def _task_branches(tree: _Tree) -> list[TaskBranch]:
    out: list[TaskBranch] = []
    for tid in tree.walk_ids():
        siblings = tree.children(tree.parent(tid)) if tree.parent(tid) else [tid]
        out.append(TaskBranch(
            id=tid, parent_id=tree.parent(tid), depth=tree.depth(tid),
            order_index=siblings.index(tid) if tid in siblings else 0,
            description=tree.description(tid),
        ))
    return out


class _EdgeAccumulator:
    def __init__(self):
        self.backbone: list[GraphEdge] = []
        self._seen: set[tuple[str, str]] = set()

    def add_backbone(self, frm: str, to: str, flow: EdgeFlow = "ascent") -> None:
        if (frm, to) not in self._seen:
            self._seen.add((frm, to))
            self.backbone.append(GraphEdge(from_node=frm, to=to, flow=flow))

    def snapshot(self, fanout: list[tuple[str, str, EdgeFlow]]) -> list[GraphEdge]:
        return list(self.backbone) + [GraphEdge(from_node=f, to=t, flow=fl) for f, t, fl in fanout]


def _evaluator_detail(p: "_Pass") -> EvaluatorDetail:
    if p is None or p.qa is None:
        return EvaluatorDetail(ran=False, success=None, score=None, reason=None)
    return EvaluatorDetail(
        ran=True, success=p.qa.success, score=p.qa.score, reason=p.qa.reason,
        criteria_results=dict(p.qa.criteria_results), judge=p.qa.judge, spec=p.qa.spec,
    )


def _dispatch_detail(p: "_Pass") -> DispatchDetail:
    return DispatchDetail(
        candidates=[CandidateInfo(agent_id=e.agent_id, passed=e.passed, fit_score=e.fit_score) for e in p.phase1],
        claims=[ClaimInfo(agent_id=e.agent_id, decision=e.decision, justification=e.justification) for e in p.phase2.values()],
        winner_agent_id=p.winner_id,
        dispatch_reason=p.dispatched.reason if p.dispatched is not None else None,
        unassigned_reason=p.unassigned.reason if p.unassigned is not None else None,
    )


def _pass_detail(input_detail: InputDetail, p: "_Pass", tid: str) -> "StepDetail":
    """StepDetail scopé sur UNE passe d'une tâche (réutilisé par les jalons de la passe)."""
    detail = StepDetail(input=input_detail)
    detail.dispatch = _dispatch_detail(p)
    detail.evaluator = _evaluator_detail(p)
    detail.testset = TestSetDetail(forked=(p.outcome == "qa_fail"), from_task_id=tid)
    winner = p.winner_id
    winner_tools = [t for t in p.tools if t.agent_id == winner] if winner else []
    for aid in p.phase1_by_agent:
        detail.agents[aid] = _agent_detail(
            aid, p.phase1_by_agent, p.phase2, winner, p.executed, p.elo, p.tags, winner_tools
        )
    if p.executed is not None:
        detail.output = OutputDetail(
            produced=True, output_summary=p.executed.output_summary,
            output_content=p.executed.output_content, llm_metadata=p.executed.llm_metadata,
        )
    return detail


def _tool_milestones(tid: str, p: "_Pass", owner_detail: "StepDetail", acc: "_EdgeAccumulator") -> list["GraphStep"]:
    winner = p.winner_id
    if winner is None:
        return []
    wnode = _nid("agent", tid, winner)
    steps: list[GraphStep] = []
    for group in _tool_groups([t for t in p.tools if t.agent_id == winner]):
        tname = group[0].tool_name
        tnode = _nid("tool", tid, tname)
        # shallow copy volontaire : .tool est le seul champ qui diverge par jalon.
        detail = owner_detail.model_copy()
        detail.tool = ToolDetail(
            agent_id=winner, tool_name=tname,
            calls=[ToolCallInfo(tool_name=c.tool_name, arguments=c.arguments,
                                result=c.result, latency_ms=c.latency_ms) for c in group],
        )
        label = f"TOOL · {tname}" + (f" ×{len(group)}" if len(group) > 1 else "")
        steps.append(GraphStep(milestone_type="tool", label=label, sub_task_id=tid,
                               active_nodes=[wnode, tnode],
                               active_edges=acc.snapshot([(wnode, tnode, "transient")]),
                               winner_agent_id=winner, outcome=p.outcome, detail=detail))
    return steps


def _exit_owner(exit_node_id: str) -> str:
    """task_id du nœud d'exit (format kind:tid[:extra] ; les task ids UUID n'ont pas de ':')."""
    return exit_node_id.split(":")[1]


def _walk(tid: str, entry_anchor: str, tree: "_Tree", runs: dict[str, "_TaskRun"],
          acc: "_EdgeAccumulator") -> list["GraphStep"]:
    run = runs.get(tid)
    steps: list[GraphStep] = []
    if run is None:
        return steps   # dep sautée : jamais tracée
    input_detail = InputDetail(task_id=tid, description=tree.description(tid),
                               required_tags=tree.tags(tid))

    # ROSTER GAP : branche réduite au cul-de-sac
    if run.roster_gap is not None:
        gid = _nid("roster_gap", tid)
        acc.add_backbone(entry_anchor, gid, "ascent")
        det = StepDetail(input=input_detail,
                         roster_gap=RosterGapDetail(missing_tags=list(run.roster_gap.missing_tags)))
        steps.append(GraphStep(milestone_type="roster_gap", label="ROSTER GAP", sub_task_id=tid,
                               active_nodes=[gid], active_edges=acc.snapshot([]),
                               outcome="roster_gap", detail=det))
        return steps

    diag_detail: DiagnosticDetail | None = None
    if run.diagnosed is not None:
        att = run.diagnosed.attribution
        diag_detail = DiagnosticDetail(
            attribution=att, reason=run.diagnosed.reason, consignes=run.diagnosed.consignes,
            route_taken=att if att != "unattributed" else "stop",
        )

    did, evid, dgid = _nid("dispatch", tid), _nid("evaluator", tid), _nid("diagnostic", tid)

    for pi, p in enumerate(run.passes):
        detail = _pass_detail(input_detail, p, tid)
        if pi > 0 and diag_detail is not None:
            detail.diagnostic = diag_detail   # la passe retry porte le diagnostic qui l'a déclenchée
        winner = p.winner_id
        suffix = " · pass 2" if pi == 1 else ""

        # DISPATCH
        acc.add_backbone(entry_anchor, did, "ascent")
        fan: list[tuple[str, str, EdgeFlow]] = []
        nodes_active = [did]
        if winner:
            fan.append((did, _nid("agent", tid, winner), "ascent"))
            nodes_active.append(_nid("agent", tid, winner))
        if pi == 1:
            fan.append((dgid, did, "transient"))   # loop-back diag→dispatch allumé au retry
        steps.append(GraphStep(milestone_type="dispatch", label=f"DISPATCH{suffix}", sub_task_id=tid,
                               pass_index=pi, active_nodes=nodes_active, active_edges=acc.snapshot(fan),
                               winner_agent_id=winner, outcome=p.outcome, detail=detail))
        if winner is None:
            continue   # unassigned : la passe s'arrête au dispatch (divider éventuel plus bas)
        wnode = _nid("agent", tid, winner)
        acc.add_backbone(did, wnode, "ascent")

        # TOOL*
        for ts in _tool_milestones(tid, p, detail, acc):
            ts.pass_index = pi
            steps.append(ts)

        # AGENT
        steps.append(GraphStep(milestone_type="agent", label=f"AGENT · {winner}{suffix}", sub_task_id=tid,
                               pass_index=pi, active_nodes=[wnode], active_edges=acc.snapshot([]),
                               winner_agent_id=winner, outcome=p.outcome, detail=detail))

        # EVALUATOR
        if p.qa is not None:
            acc.add_backbone(wnode, evid, "descent")
            steps.append(GraphStep(milestone_type="evaluator", label=f"EVALUATOR{suffix}", sub_task_id=tid,
                                   pass_index=pi, active_nodes=[evid], active_edges=acc.snapshot([]),
                                   winner_agent_id=winner, outcome=p.outcome, detail=detail))

        # Chaîne D3 après la passe 0 : DIAGNOSTIC (+ EVAL v2 sur route evaluator)
        if pi == 0 and diag_detail is not None:
            acc.add_backbone(evid, dgid, "descent")
            ddetail = detail.model_copy()
            ddetail.diagnostic = diag_detail
            steps.append(GraphStep(milestone_type="diagnostic",
                                   label=f"DIAGNOSTIC · route {diag_detail.route_taken}",
                                   sub_task_id=tid, active_nodes=[dgid],
                                   active_edges=acc.snapshot([]), winner_agent_id=winner,
                                   outcome="diagnosed", detail=ddetail))
            if run.reeval is not None:
                vdetail = ddetail.model_copy()
                vdetail.evaluator = EvaluatorDetail(
                    ran=True, success=run.reeval.success, score=run.reeval.score,
                    reason=run.reeval.reason, criteria_results=dict(run.reeval.criteria_results),
                    judge=run.reeval.judge, spec=run.reeval.spec,
                )
                steps.append(GraphStep(milestone_type="evaluator", label="EVALUATOR v2", sub_task_id=tid,
                                       active_nodes=[evid],
                                       active_edges=acc.snapshot([(dgid, evid, "transient")]),
                                       winner_agent_id=winner,
                                       outcome="qa_pass" if run.reeval.success else "qa_fail",
                                       detail=vdetail))

    # DIVISION (D1 recovery ou D3 task_spec) — paire par niveau
    if run.divided is not None:
        dvid = _nid("divider", tid)
        acc.add_backbone(_divider_anchor(run, tid) or entry_anchor, dvid, "ascent")
        div_detail = StepDetail(input=input_detail, divider=DividerDetail(
            divided=True, origin=_division_origin(run),
            sub_tasks=[DividerSubTaskInfo(id=st.id, description=st.description,
                                          depends_on=list(st.depends_on),
                                          required_tags=dict(st.required_tags or {}))
                       for st in run.divided.sub_tasks],
        ))
        if diag_detail is not None:
            div_detail.diagnostic = diag_detail
        steps.append(GraphStep(milestone_type="divider", label="DIVIDER", sub_task_id=tid,
                               active_nodes=[dvid], active_edges=acc.snapshot([]),
                               outcome="divided", detail=div_detail))

        sinks = _sink_ids(run.divided, runs)
        total, collected = len(sinks), 0
        agid = _nid("aggregator", tid)
        for c in tree.children(tid):
            child_steps = _walk(c, dvid, tree, runs, acc)
            # récit de collecte : le dernier jalon d'un sink validé allume l'aggregator parent
            if run.aggregated is not None and c in sinks and child_steps and _has_result(c, runs):
                collected += 1
                ex_node = _exit_node(c, runs)
                acc.add_backbone(ex_node, agid, "descent")
                last = child_steps[-1]
                last.active_nodes = list(last.active_nodes) + [agid]
                last.active_edges = list(last.active_edges) + [
                    GraphEdge(from_node=ex_node, to=agid, flow="descent")]
                d2 = last.detail.model_copy()
                d2.aggregator = AggregatorDetail(aggregated=False, collected=collected, total=total)
                last.detail = d2
            steps += child_steps

        if run.aggregated is not None:
            agg_detail = StepDetail(input=input_detail, aggregator=AggregatorDetail(
                aggregated=True, sub_task_ids=list(run.aggregated.sub_task_ids),
                output_summary=run.aggregated.output_summary,
                output_content=run.aggregated.output_content,
                collected=collected, total=total,
            ))
            agg_detail.output = OutputDetail(
                produced=True, output_summary=run.aggregated.output_summary,
                output_content=run.aggregated.output_content,
                llm_metadata=run.aggregated.llm_metadata,
            )
            steps.append(GraphStep(milestone_type="aggregator", label="AGGREGATOR", sub_task_id=tid,
                                   active_nodes=[agid], active_edges=acc.snapshot([]),
                                   outcome="divided", detail=agg_detail))
    return steps


def _output_detail(exit_id: str, runs: dict[str, "_TaskRun"]) -> "OutputDetail":
    owner = runs[_exit_owner(exit_id)]
    if exit_id.startswith("aggregator:"):
        ev = owner.aggregated
        return OutputDetail(produced=True, output_summary=ev.output_summary,
                            output_content=ev.output_content, llm_metadata=ev.llm_metadata)
    executed = owner.passes[-1].executed
    return OutputDetail(produced=True, output_summary=executed.output_summary,
                        output_content=executed.output_content, llm_metadata=executed.llm_metadata)


def _attach_todos(steps: list[GraphStep], tree: "_Tree", runs: dict[str, "_TaskRun"]) -> None:
    """Post-processing : TODO hiérarchique par jalon (révélation au DIVIDER parent,
    parent_id/depth/first_step_index/note). Mute les steps en place."""
    if not steps:
        return
    first_step: dict[str, int] = {}
    last_subtree: dict[str, int] = {}
    reveal: dict[str, int] = {tree.root_id: 0}

    def chain(tid: str | None) -> list[str]:
        out: list[str] = []
        cur = tid
        while cur is not None:
            out.append(cur)
            cur = tree.parent(cur)
        return out

    for i, s in enumerate(steps):
        if s.sub_task_id is None:
            continue
        first_step.setdefault(s.sub_task_id, i)
        for a in chain(s.sub_task_id):
            last_subtree[a] = i
        if s.milestone_type == "divider":
            for c in tree.children(s.sub_task_id):
                reveal.setdefault(c, i)

    def resolved_state(tid: str) -> Literal["done", "failed", "pending"]:
        run = runs.get(tid)
        if run is None:
            return "pending"   # jamais exécutée (dep sautée)
        return "done" if _has_result(tid, runs) else "failed"

    def note_of(tid: str) -> str | None:
        run = runs.get(tid)
        if run is None:
            return None
        if run.roster_gap is not None:
            return "roster gap"
        parts: list[str] = []
        if run.diagnosed is not None:
            parts.append(f"route {run.diagnosed.attribution}")
        if len(run.passes) > 1:
            parts.append("pass 2")
        return " · ".join(parts) or None

    order = tree.walk_ids()
    for i, s in enumerate(steps):
        cur_chain = set(chain(s.sub_task_id)) if s.sub_task_id else {tree.root_id}
        items: list[TodoItem] = []
        for tid in order:
            ri = reveal.get(tid)
            if ri is None or ri > i:
                continue
            is_root = tid == tree.root_id
            if is_root and s.milestone_type == "output":
                state: Literal["pending", "current", "done", "failed"] = "done"
            elif tid in cur_chain:
                terminal = last_subtree.get(tid, -1) == i and tid == s.sub_task_id
                if terminal and not _has_result(tid, runs):
                    state = "failed"     # dernier jalon de la tâche, sans résultat : mort constatée
                elif (tid == s.sub_task_id and s.milestone_type == "evaluator"
                        and s.outcome == "qa_fail"):
                    state = "failed"
                else:
                    state = "current"
            elif last_subtree.get(tid, -1) < i:
                state = resolved_state(tid)
            else:
                state = "pending"
            items.append(TodoItem(
                id=tid, description=tree.description(tid), state=state, is_root=is_root,
                parent_id=tree.parent(tid), depth=tree.depth(tid),
                first_step_index=first_step.get(tid, 0 if is_root else None),
                note=note_of(tid),
            ))
        s.todo = items


def _build_steps(tree: "_Tree", runs: dict[str, "_TaskRun"],
                 session_meta: "SessionMeta | None") -> list["GraphStep"]:
    root_record = _meta_record(session_meta, tree.root_id)
    root_input = _make_input_detail(root_record, tree.root_id)
    root_tags = tree.tags(tree.root_id)
    acc = _EdgeAccumulator()
    steps: list[GraphStep] = [GraphStep(
        milestone_type="input", label="INPUT", sub_task_id=tree.root_id, active_nodes=["input"],
        active_edges=acc.snapshot([]), outcome="no_qa", detail=StepDetail(input=root_input))]

    trunk_anchor = "input"
    if root_tags:
        acc.add_backbone("input", "tagger", "ascent")
        steps.append(GraphStep(milestone_type="tagger", label="TAGGER", sub_task_id=tree.root_id,
                               active_nodes=["tagger"], active_edges=acc.snapshot([]),
                               outcome="no_qa", detail=StepDetail(input=root_input)))
        trunk_anchor = "tagger"

    steps += _walk(tree.root_id, trunk_anchor, tree, runs, acc)

    final_exit = _exit_node(tree.root_id, runs)
    if final_exit:
        acc.add_backbone(final_exit, "output", "descent")
        out_detail = StepDetail(input=root_input, output=_output_detail(final_exit, runs))
        root_run = runs.get(tree.root_id)
        steps.append(GraphStep(
            milestone_type="output", label="OUTPUT", sub_task_id=tree.root_id,
            active_nodes=["output"], active_edges=acc.snapshot([]),
            outcome="divided" if (root_run and root_run.divided) else
                    (root_run.passes[-1].outcome if root_run and root_run.passes else "no_qa"),
            detail=out_detail))
    _attach_todos(steps, tree, runs)
    return steps


def build_graph(events: list[ClaimEvent], session_meta: SessionMeta | None = None) -> GraphModel:
    tree = _build_tree(events, session_meta)
    runs = _parse_runs(events)
    nodes, edges = _build_structure(tree, runs, tree.tags(tree.root_id))
    steps = _build_steps(tree, runs, session_meta)
    return GraphModel(nodes=nodes, edges=edges, steps=steps, tasks=_task_branches(tree))
