# V3 Observabilité Vague 2 — Frontend : graphe cumulatif par jalons Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transformer le graphe du tab Sessions d'un instantané par tâche en un rejeu cumulatif jalon-par-jalon d'un run unique (divisé ou simple), avec une 4e tier `tools`, une TODO vivante, et des modals divider/aggregator/tool + spec à l'evaluator.

**Architecture:** Réécriture de `build_graph` (fonction pure) du modèle « un step = une tâche » vers « un step = un jalon » (`input/divider/dispatch/agent/tool/evaluator/aggregator/output`). Un run divisé est une seule `GraphModel` couvrant la tâche parente (events `task_divided`/`task_aggregated`) plus les events de chaque sous-tâche (task_ids distincts, absents de `meta.tasks`). Le builder descend dans les sous-tâches via l'ordre d'émission réel de la trace. Les nœuds tools (canopée idle) viennent des `ToolCalledEvent`. Les arêtes backbone sont cumulatives/persistantes, les arêtes fan-out (`dispatch→agent`, `agent→tool`, `agent→evaluator`) transitoires. Le frontend (vanilla JS/SVG) consomme le nouveau `GraphModel` : 4 bandes, allumage cumulatif, TODO snapshot par jalon, nouveaux modals.

**Tech Stack:** Python 3.14, Pydantic 2.13, pytest 9 (backend pur, TDD) ; vanilla JS + SVG (frontend, validé navigateur, hors TDD auto, conforme V2c).

---

## Contexte et références

- **Deep-dive (design verrouillé)** : `docs/superpowers/epics/v3-observabilite-vague2-frontend.md`
- **Corrections issues de la validation des traces réelles (étape 1, 2026-06-02)** intégrées dans ce plan :
  1. **Ordre TOOL avant AGENT** : les `tool_called` sont émis pendant l'exécution, avant l'`executed`. Séquence par sous-tâche = `DISPATCH → TOOL(×n) → AGENT → EVALUATOR`.
  2. **ELO plié dans EVALUATOR** : `elo_updated` n'est pas un jalon ; il alimente le détail evaluator/agent.
  3. **INPUT/OUTPUT synthétisés** : aucun event « input » ; INPUT dérivé de `session_meta`, OUTPUT de `task_aggregated` (ou du dernier `executed` en run simple).
  4. **Granularité tools = RLE par nom** : appels consécutifs du même `tool_name` fusionnés en un jalon TOOL (compteur + liste des appels dans le modal agent), reset au tool différent suivant.
  5. **Fallback aggregator non détectable depuis la trace** (aucun signal d'event) → hors périmètre ; `AggregatorDetail` ne porte pas de flag fallback.
- **Trace réelle de référence** (run divisé `run_demo_v3`, gitignored) : `runs/sessions/2026-06-02T09-24-21-12a72561/trace.jsonl` (6 sous-tâches, 4 tools distincts, spec par sous-tâche). Sert de fixture d'intégration en Task 6.
- **Fichiers événements/schémas (ne PAS modifier, vague 1 figée)** : `src/aaosa/tracing/events.py`, `src/aaosa/qa/spec.py`, `src/aaosa/tracing/store.py`.

## Périmètre verrouillé

- Tab Sessions + réécriture `build_graph` (partagée → impacte aussi `case_graph` du health tab, qui devient un rejeu par jalons d'un cas single-task).
- Couche tools : canopée idle visible si le run a une activité tool ; `agent→tool` s'allume à l'appel.
- Parcours B2/B3 (triage→fix) : **différé**.
- États QA-fail et unassigned : couverts par fixtures synthétiques (aucun échantillon dans la trace réelle).
- Pas de nouvelle langue visuelle : on étend l'instrument verrouillé (`DESIGN.md`/`PRODUCT.md`).

## Structure de fichiers

| Fichier | Responsabilité | Action |
| --- | --- | --- |
| `dashboard/graph_model.py` | Modèle de graphe + builder pur (réécriture milestones) | Réécrire |
| `tests/dashboard/test_graph_model.py` | Tests unitaires schéma + builder | Réécrire (le modèle change) |
| `tests/dashboard/test_build_graph_a4.py` | Tests run divisé | Réécrire vers milestones |
| `tests/dashboard/test_build_graph_milestones.py` | Nouveaux tests jalons/tools/todo/états | Créer |
| `tests/dashboard/test_serialization.py` | Sérialisation `GraphModel` (alias `from`) | Étendre |
| `dashboard/collectors/sessions.py` | `session_detail` → `build_graph` | Vérifier (signature inchangée) |
| `dashboard/collectors/health_checks.py` | `case_graph` → `build_graph` | Vérifier (single-task) |
| `dashboard/static/js/graph.js` | Rendu SVG : 4 bandes, tools, allumage cumulatif | Modifier |
| `dashboard/static/js/modal.js` | Modals divider/aggregator/tool + spec evaluator | Modifier |
| `dashboard/static/js/tabs/sessions.js` | TODO snapshot + labels scrubber par jalon | Modifier |
| `dashboard/static/css/*.css` | Bande tools, sous-items todo, champs modals | Modifier |

---

## PARTIE A — Backend `build_graph` (TDD, pur)

Le nouveau `GraphModel` conserve `nodes`/`edges`/`steps`. **`GraphStep` devient un jalon** (pas une tâche). On réutilise au maximum les types de détail existants (`InputDetail`, `DispatchDetail`, `AgentDetail`, `EvaluatorDetail`, `OutputDetail`, `TestSetDetail`) et on en ajoute trois (`DividerDetail`, `AggregatorDetail`, `ToolDetail`) + un type TODO.

### Contrat cible du modèle (référence pour toutes les tasks)

```python
NodeLayer = Literal["tools", "bottom", "center", "top"]
NodeType = Literal["input", "dispatch", "evaluator", "output", "testset", "agent", "divider", "aggregator", "tool"]
MilestoneType = Literal["input", "divider", "dispatch", "agent", "tool", "evaluator", "aggregator", "output"]
Outcome = Literal["qa_pass", "qa_fail", "unassigned", "no_qa", "divided"]
```

- Bandes : `tools` (canopée, visuellement la plus haute), `bottom` (agents), `center` (logique), `top` (in/out, visuellement la plus basse). Le JS inverse déjà l'ordre vertical ; on ajoute `tools` au-dessus de `bottom`.
- Nœud tool : `id = "tool:" + tool_name`, `layer="tools"`, `type="tool"`, `label=tool_name`.
- Arête `agent→tool` : `from=agent_id`, `to="tool:"+tool_name`.

---

### Task 1: Schéma — nouveaux types de détail + GraphStep jalon

**Files:**
- Modify: `dashboard/graph_model.py` (lignes 22-143 : types)
- Test: `tests/dashboard/test_graph_model.py` (réécriture des tests de schéma)

- [ ] **Step 1: Écrire les tests de schéma (nouveau modèle)**

Remplacer le contenu de `tests/dashboard/test_graph_model.py` par les tests ci-dessous (on garde les helpers `p1/p2/disp/ex/qa/elo/tag` pour les tasks suivantes). Ce step ne garde QUE les tests de schéma ; les tests de builder arriveront dans les tasks suivantes.

```python
from datetime import datetime, timezone

from aaosa.qa.spec import CriterionSpec, EvaluatorSpec
from aaosa.schemas.output import LLMMetadata
from aaosa.tracing.events import (
    DispatchedEvent,
    DividedSubTask,
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
from dashboard.graph_model import (
    AggregatorDetail,
    DividerDetail,
    DividerSubTaskInfo,
    EvaluatorDetail,
    GraphEdge,
    GraphModel,
    GraphNode,
    GraphStep,
    StepDetail,
    ToolCallInfo,
    ToolDetail,
    TodoItem,
    build_graph,
)

SID = "sess-1"


def p1(tid, aid, passed=True, fit=0.8):
    return Phase1FilteredEvent(session_id=SID, task_id=tid, agent_id=aid, passed=passed, fit_score=fit)


def p2(tid, aid, decision="claim", just="mine"):
    return Phase2ClaimedEvent(session_id=SID, task_id=tid, agent_id=aid, decision=decision, justification=just)


def disp(tid, aid, reason="best fit"):
    return DispatchedEvent(session_id=SID, task_id=tid, agent_id=aid, reason=reason)


def ex(tid, aid, summary="out", content="full output", meta=None):
    return ExecutedEvent(session_id=SID, task_id=tid, agent_id=aid, output_summary=summary, output_content=content, llm_metadata=meta)


def unassigned(tid, reason="no agent"):
    return UnassignedEvent(session_id=SID, task_id=tid, reason=reason)


def qa(tid, aid, success=True, score=1.0, reason="ok", criteria=None, judge=None, spec=None):
    return QAEvaluatedEvent(session_id=SID, task_id=tid, agent_id=aid, success=success, score=score, reason=reason, criteria_results=criteria or {}, judge=judge, spec=spec)


def elo(tid, aid, deltas):
    return EloUpdatedEvent(session_id=SID, task_id=tid, agent_id=aid, deltas=deltas)


def tag(tid, aid, t, initial):
    return TagAcquiredEvent(session_id=SID, task_id=tid, agent_id=aid, tag=t, initial_elo=initial)


def tool(tid, aid, name, args=None, result="r", latency=0.5):
    return ToolCalledEvent(session_id=SID, task_id=tid, agent_id=aid, tool_name=name, arguments=args or {}, result=result, latency_ms=latency)


class TestGraphEdgeAlias:
    def test_from_alias_in_json(self):
        edge = GraphEdge(from_node="input", to="dispatch")
        assert edge.model_dump(by_alias=True) == {"from": "input", "to": "dispatch"}

    def test_construct_by_field_name(self):
        edge = GraphEdge(from_node="a", to="b")
        assert edge.from_node == "a" and edge.to == "b"


class TestNewDetailTypes:
    def test_divider_detail(self):
        d = DividerDetail(divided=True, sub_tasks=[DividerSubTaskInfo(id="s1", description="x", depends_on=[])])
        assert d.divided is True and d.sub_tasks[0].id == "s1"

    def test_aggregator_detail(self):
        d = AggregatorDetail(aggregated=True, sub_task_ids=["s1"], output_summary="s", output_content="c")
        assert d.sub_task_ids == ["s1"]

    def test_tool_detail_groups_calls(self):
        d = ToolDetail(agent_id="ag", tool_name="grep", calls=[ToolCallInfo(tool_name="grep", arguments={"p": "x"}, result="r", latency_ms=0.1)])
        assert d.tool_name == "grep" and len(d.calls) == 1

    def test_evaluator_detail_carries_spec(self):
        spec = EvaluatorSpec(criteria=[CriterionSpec(name="non_empty", gate=True)])
        d = EvaluatorDetail(ran=True, success=True, score=1.0, reason="ok", criteria_results={"non_empty": True}, judge=None, spec=spec)
        assert d.spec.criteria[0].name == "non_empty"

    def test_todo_item(self):
        t = TodoItem(id="s1", description="x", state="current", is_root=False)
        assert t.state == "current" and t.is_root is False


class TestGraphStepIsMilestone:
    def test_step_has_milestone_fields(self):
        node = GraphNode(id="input", layer="top", type="input", label="Input")
        step = GraphStep(
            milestone_type="input", label="INPUT", sub_task_id=None, order_index=None,
            active_nodes=["input"], active_edges=[], winner_agent_id=None, outcome="no_qa",
            detail=StepDetail.empty(task_id="t1", description="d"), todo=[],
        )
        model = GraphModel(nodes=[node], edges=[], steps=[step])
        assert model.steps[0].milestone_type == "input"
        assert model.steps[0].active_nodes == ["input"]
```

- [ ] **Step 2: Lancer les tests, vérifier qu'ils échouent**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_graph_model.py -v`
Expected: FAIL (ImportError sur `DividerDetail`, `ToolDetail`, `TodoItem`, `StepDetail.empty`, et `GraphStep` n'accepte pas `milestone_type`).

- [ ] **Step 3: Réécrire la section types de `dashboard/graph_model.py`**

Remplacer les lignes 22-143 (de `NodeLayer = ...` jusqu'à la fin de `class GraphModel`) par :

```python
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
```

Mettre à jour le bloc d'import en tête de fichier pour ajouter `EvaluatorSpec` :

```python
from aaosa.qa.spec import EvaluatorSpec
```

(Ajouter sous l'import `from aaosa.qa.judge import JudgeBreakdown`.)

- [ ] **Step 4: Lancer les tests de schéma, vérifier le PASS**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_graph_model.py::TestGraphEdgeAlias tests/dashboard/test_graph_model.py::TestNewDetailTypes tests/dashboard/test_graph_model.py::TestGraphStepIsMilestone -v`
Expected: PASS (10 tests). Les anciennes fonctions builder de `graph_model.py` (lignes 146+) sont maintenant cassées vis-à-vis du nouveau `GraphStep` — c'est attendu, elles sont réécrites en Task 2-5. `build_graph` ne tournera pas encore.

- [ ] **Step 5: Commit**

```bash
git add dashboard/graph_model.py tests/dashboard/test_graph_model.py
git commit -m "feat(v2-frontend): schéma GraphStep jalon + détails divider/aggregator/tool/todo"
```

---

### Task 2: Builder — nœuds & arêtes (incl. tier tools)

**Files:**
- Modify: `dashboard/graph_model.py` (réécrire `_build_nodes`, `_build_edges`, ajouter helpers tools)
- Test: `tests/dashboard/test_build_graph_milestones.py` (créer)

- [ ] **Step 1: Écrire les tests de nœuds/arêtes**

Créer `tests/dashboard/test_build_graph_milestones.py` :

```python
from aaosa.tracing.events import (
    DividedSubTask,
    ExecutedEvent,
    Phase1FilteredEvent,
    Phase2ClaimedEvent,
    DispatchedEvent,
    QAEvaluatedEvent,
    TaskAggregatedEvent,
    TaskDividedEvent,
    ToolCalledEvent,
)
from dashboard.graph_model import _build_nodes, _build_edges, _tool_node_id

SID = "s"


def _tool(tid, aid, name):
    return ToolCalledEvent(session_id=SID, task_id=tid, agent_id=aid, tool_name=name, arguments={}, result="r", latency_ms=0.1)


class TestNodes:
    def test_base_nodes_present(self):
        nodes = _build_nodes([])
        ids = {n.id for n in nodes}
        assert {"input", "dispatch", "evaluator", "output", "testset"} <= ids

    def test_tool_nodes_from_distinct_tool_names(self):
        events = [_tool("t1", "ag", "grep"), _tool("t1", "ag", "grep"), _tool("t1", "ag", "read")]
        nodes = _build_nodes(events)
        tool_nodes = [n for n in nodes if n.type == "tool"]
        assert {n.id for n in tool_nodes} == {_tool_node_id("grep"), _tool_node_id("read")}
        assert all(n.layer == "tools" for n in tool_nodes)
        assert {n.label for n in tool_nodes} == {"grep", "read"}

    def test_divider_aggregator_nodes_only_when_divided(self):
        assert "divider" not in {n.id for n in _build_nodes([])}
        divided = [TaskDividedEvent(session_id=SID, task_id="p", sub_tasks=[DividedSubTask(id="s1", description="x")])]
        ids = {n.id for n in _build_nodes(divided)}
        assert "divider" in ids and "aggregator" in ids


class TestEdges:
    def test_agent_tool_edges(self):
        events = [_tool("t1", "ag", "grep")]
        nodes = _build_nodes(events)
        edges = _build_edges(nodes, events)
        pairs = {(e.from_node, e.to) for e in edges}
        assert ("ag", _tool_node_id("grep")) in pairs

    def test_divider_backbone_edges(self):
        divided = [TaskDividedEvent(session_id=SID, task_id="p", sub_tasks=[DividedSubTask(id="s1", description="x")])]
        nodes = _build_nodes(divided)
        edges = _build_edges(nodes, divided)
        pairs = {(e.from_node, e.to) for e in edges}
        assert ("input", "divider") in pairs
        assert ("divider", "aggregator") in pairs
        assert ("aggregator", "output") in pairs
```

- [ ] **Step 2: Lancer, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_build_graph_milestones.py -v`
Expected: FAIL (ImportError sur `_tool_node_id`, signature `_build_edges` changée).

- [ ] **Step 3: Réécrire `_build_nodes`/`_build_edges` + helpers**

Dans `dashboard/graph_model.py`, remplacer `_build_nodes` (lignes ~175-188) et `_build_edges` (lignes ~191-203) par :

```python
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
```

Ajouter `ToolCalledEvent` à l'import depuis `aaosa.tracing.events` en tête de `graph_model.py`.

- [ ] **Step 4: Lancer, vérifier le PASS**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_build_graph_milestones.py::TestNodes tests/dashboard/test_build_graph_milestones.py::TestEdges -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add dashboard/graph_model.py tests/dashboard/test_build_graph_milestones.py
git commit -m "feat(v2-frontend): tier tools (nœuds + arêtes agent→tool) dans build_graph"
```

---

### Task 3: Builder — moteur de jalons, run simple

Établit le moteur `_build_milestones` + l'accumulation d'arêtes (backbone persistant / fan-out transitoire) pour un run **non divisé** : `INPUT → DISPATCH → AGENT → EVALUATOR → OUTPUT`. C'est aussi le chemin emprunté par `case_graph` (health, single-task).

**Files:**
- Modify: `dashboard/graph_model.py` (remplacer `_build_step`/`_active_path`, réécrire `build_graph`)
- Test: `tests/dashboard/test_build_graph_milestones.py`

- [ ] **Step 1: Écrire les tests du run simple**

Ajouter à `tests/dashboard/test_build_graph_milestones.py` :

```python
from aaosa.tracing.store import SessionMeta, SessionTaskRecord
from dashboard.graph_model import build_graph


def _meta(task_id, desc, tags=None):
    return SessionMeta(
        session_id=SID, started_at="2026-01-01T00:00:00Z", ended_at="2026-01-01T00:01:00Z",
        tasks=[SessionTaskRecord(id=task_id, description=desc, winner_agent_id=None, outcome="qa_pass", required_tags=tags or {})],
        agent_ids=["ag"],
    )


def _simple_run(tid="t1", aid="ag", success=True):
    return [
        Phase1FilteredEvent(session_id=SID, task_id=tid, agent_id=aid, passed=True, fit_score=0.9),
        Phase2ClaimedEvent(session_id=SID, task_id=tid, agent_id=aid, decision="claim", justification="mine"),
        DispatchedEvent(session_id=SID, task_id=tid, agent_id=aid, reason="sole claimer"),
        ExecutedEvent(session_id=SID, task_id=tid, agent_id=aid, output_summary="sum", output_content="content"),
        QAEvaluatedEvent(session_id=SID, task_id=tid, agent_id=aid, success=success, score=1.0 if success else 0.0, reason="r"),
    ]


class TestSimpleRunMilestones:
    def test_milestone_sequence(self):
        graph = build_graph(_simple_run(), _meta("t1", "do it"))
        assert [s.milestone_type for s in graph.steps] == ["input", "dispatch", "agent", "evaluator", "output"]

    def test_input_milestone_synthesized_from_meta(self):
        graph = build_graph(_simple_run(), _meta("t1", "do it", {"backend": 70}))
        inp = graph.steps[0]
        assert inp.active_nodes == ["input"]
        assert inp.detail.input.description == "do it"
        assert inp.detail.input.required_tags == {"backend": 70}

    def test_dispatch_milestone_lights_input_dispatch_and_winner(self):
        graph = build_graph(_simple_run(), _meta("t1", "do it"))
        disp_step = next(s for s in graph.steps if s.milestone_type == "dispatch")
        assert "dispatch" in disp_step.active_nodes and "ag" in disp_step.active_nodes
        pairs = {(e.from_node, e.to) for e in disp_step.active_edges}
        assert ("input", "dispatch") in pairs   # backbone
        assert ("dispatch", "ag") in pairs       # fan-out
        assert disp_step.winner_agent_id == "ag"

    def test_agent_milestone_carries_output(self):
        graph = build_graph(_simple_run(), _meta("t1", "do it"))
        agent_step = next(s for s in graph.steps if s.milestone_type == "agent")
        assert agent_step.active_nodes == ["ag"]
        assert agent_step.detail.agents["ag"].output_content == "content"

    def test_evaluator_milestone_pass(self):
        graph = build_graph(_simple_run(success=True), _meta("t1", "do it"))
        ev = next(s for s in graph.steps if s.milestone_type == "evaluator")
        assert ev.outcome == "qa_pass"
        assert "evaluator" in ev.active_nodes
        pairs = {(e.from_node, e.to) for e in ev.active_edges}
        assert ("ag", "evaluator") in pairs

    def test_output_milestone_backbone_persists(self):
        graph = build_graph(_simple_run(), _meta("t1", "do it"))
        out = graph.steps[-1]
        assert out.milestone_type == "output"
        assert "output" in out.active_nodes
        pairs = {(e.from_node, e.to) for e in out.active_edges}
        assert ("input", "dispatch") in pairs   # backbone cumulatif toujours présent
        assert ("evaluator", "output") in pairs
        assert out.detail.output.output_content == "content"
```

- [ ] **Step 2: Lancer, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_build_graph_milestones.py::TestSimpleRunMilestones -v`
Expected: FAIL (`build_graph` casse — `_build_step` produit l'ancien modèle).

- [ ] **Step 3: Implémenter le moteur de jalons**

Dans `dashboard/graph_model.py`, **supprimer** `_active_path` (lignes ~233-260) et `_build_step` (lignes ~263-364), puis **réécrire** `build_graph` (lignes ~367-375) et ajouter les helpers. Nouveau bloc (du début de `_active_path` jusqu'à la fin du fichier) :

```python
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
```

Puis remplacer `build_graph` par le squelette suivant (étendu en Task 4-7) :

```python
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
```

Implémenter `_milestones_simple` (le run divisé arrive en Task 5) :

```python
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

    # TOOL milestones (Task 4 les ajoute ici) ; le caller assigne le todo
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
```

Ajouter des stubs temporaires (remplacés en Task 4 et 6) pour que le module importe :

```python
def _tool_milestones(run, detail, acc, tid):  # remplacé en Task 4
    return []


def _todo_simple(record, tid, milestone, run):  # remplacé en Task 6
    return []
```

Garder `_meta_record`, `_segment_runs`, `_agent_ids`, `_events_by_task`, `_order_task_ids` tels quels (toujours utiles ; `_order_task_ids`/`_segment_runs`/`_events_by_task` peuvent rester même si inutilisés par le nouveau `build_graph` — ne pas les supprimer, Task 8 nettoie si besoin).

- [ ] **Step 4: Lancer, vérifier le PASS**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_build_graph_milestones.py::TestSimpleRunMilestones -v`
Expected: PASS (6 tests). (Les tests TODO et tools échoueront encore car stubés — c'est attendu, ils sont activés en Task 4 et 6.)

- [ ] **Step 5: Commit**

```bash
git add dashboard/graph_model.py tests/dashboard/test_build_graph_milestones.py
git commit -m "feat(v2-frontend): moteur de jalons run simple + accumulation d'arêtes"
```

---

### Task 4: Builder — jalons TOOL (RLE)

**Files:**
- Modify: `dashboard/graph_model.py` (`_tool_milestones`)
- Test: `tests/dashboard/test_build_graph_milestones.py`

- [ ] **Step 1: Écrire les tests RLE**

Ajouter à `tests/dashboard/test_build_graph_milestones.py` :

```python
class TestToolMilestones:
    def _run_with_tools(self, names):
        tid, aid = "t1", "ag"
        evs = [
            Phase1FilteredEvent(session_id=SID, task_id=tid, agent_id=aid, passed=True, fit_score=0.9),
            DispatchedEvent(session_id=SID, task_id=tid, agent_id=aid, reason="sole claimer"),
        ]
        evs += [ToolCalledEvent(session_id=SID, task_id=tid, agent_id=aid, tool_name=n, arguments={"i": i}, result="r", latency_ms=0.1) for i, n in enumerate(names)]
        evs += [
            ExecutedEvent(session_id=SID, task_id=tid, agent_id=aid, output_summary="s", output_content="c"),
            QAEvaluatedEvent(session_id=SID, task_id=tid, agent_id=aid, success=True, score=1.0, reason="r"),
        ]
        return evs

    def test_consecutive_same_tool_collapses(self):
        # grep, grep, read, grep -> 3 jalons tool
        graph = build_graph(self._run_with_tools(["grep", "grep", "read", "grep"]), _meta("t1", "x"))
        tool_steps = [s for s in graph.steps if s.milestone_type == "tool"]
        assert [s.detail.tool.tool_name for s in tool_steps] == ["grep", "read", "grep"]
        assert len(tool_steps[0].detail.tool.calls) == 2   # 2 grep fusionnés
        assert len(tool_steps[2].detail.tool.calls) == 1

    def test_tool_milestone_lights_agent_and_tool(self):
        graph = build_graph(self._run_with_tools(["grep"]), _meta("t1", "x"))
        ts = next(s for s in graph.steps if s.milestone_type == "tool")
        assert "ag" in ts.active_nodes and "tool:grep" in ts.active_nodes
        pairs = {(e.from_node, e.to) for e in ts.active_edges}
        assert ("dispatch", "ag") in pairs   # dispatch→agent reste allumé tant que k actif
        assert ("ag", "tool:grep") in pairs

    def test_tool_milestones_between_dispatch_and_agent(self):
        graph = build_graph(self._run_with_tools(["grep"]), _meta("t1", "x"))
        types = [s.milestone_type for s in graph.steps]
        assert types == ["input", "dispatch", "tool", "agent", "evaluator", "output"]
```

- [ ] **Step 2: Lancer, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_build_graph_milestones.py::TestToolMilestones -v`
Expected: FAIL (`_tool_milestones` stub renvoie `[]`).

- [ ] **Step 3: Implémenter `_tool_milestones`**

Remplacer le stub `_tool_milestones` par :

```python
def _tool_milestones(run: "_SubTaskRun", input_detail_owner: StepDetail, acc: _EdgeAccumulator, tid: str) -> list[GraphStep]:
    winner = run.winner_id
    if winner is None:
        return []
    winner_tools = [t for t in run.tools if t.agent_id == winner]
    steps: list[GraphStep] = []
    for group in _tool_groups(winner_tools):
        tname = group[0].tool_name
        tool_node = _tool_node_id(tname)
        # detail scopé tool pour ce jalon (réutilise le StepDetail de la sous-tâche, surcharge .tool)
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
                               todo=[]))   # le caller (_milestones_simple/_milestones_divided) assigne le todo
    return steps
```

Note : `_tool_milestones` reçoit `detail` (le `StepDetail` scopé de la sous-tâche) en 2e argument depuis `_milestones_simple`/`_milestones_divided`. Il laisse `todo=[]` ; chaque caller l'assigne (`_todo_simple` côté simple, `_todo_divided` côté divisé) — c'est pourquoi le caller boucle sur les steps retournés au lieu d'un `extend` direct.

- [ ] **Step 4: Lancer, vérifier le PASS**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_build_graph_milestones.py::TestToolMilestones tests/dashboard/test_build_graph_milestones.py::TestSimpleRunMilestones -v`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add dashboard/graph_model.py tests/dashboard/test_build_graph_milestones.py
git commit -m "feat(v2-frontend): jalons TOOL avec RLE par nom de tool"
```

---

### Task 5: Builder — run divisé (divider, sous-tâches, aggregator)

**Files:**
- Modify: `dashboard/graph_model.py` (`_milestones_divided`)
- Test: `tests/dashboard/test_build_graph_milestones.py` + réécriture `tests/dashboard/test_build_graph_a4.py`

- [ ] **Step 1: Écrire les tests du run divisé**

Ajouter à `tests/dashboard/test_build_graph_milestones.py` :

```python
def _divided_meta(parent_id, desc):
    return SessionMeta(
        session_id=SID, started_at="2026-01-01T00:00:00Z", ended_at="2026-01-01T00:01:00Z",
        tasks=[SessionTaskRecord(id=parent_id, description=desc, winner_agent_id=None, outcome="divided", required_tags={})],
        agent_ids=["ag"],
    )


def _divided_events():
    """Parent divisé en 2 sous-tâches séquentielles, chacune dispatchée à ag, l'une avec un tool."""
    P, S1, S2 = "parent", "sub1", "sub2"
    return [
        TaskDividedEvent(session_id=SID, task_id=P, sub_tasks=[
            DividedSubTask(id=S1, description="investigate", depends_on=[]),
            DividedSubTask(id=S2, description="fix", depends_on=[S1]),
        ]),
        # sous-tâche 1 (avec tool)
        Phase1FilteredEvent(session_id=SID, task_id=S1, agent_id="ag", passed=True, fit_score=0.9),
        DispatchedEvent(session_id=SID, task_id=S1, agent_id="ag", reason="sole claimer"),
        ToolCalledEvent(session_id=SID, task_id=S1, agent_id="ag", tool_name="grep", arguments={}, result="r", latency_ms=0.1),
        ExecutedEvent(session_id=SID, task_id=S1, agent_id="ag", output_summary="s1", output_content="c1"),
        QAEvaluatedEvent(session_id=SID, task_id=S1, agent_id="ag", success=True, score=1.0, reason="r"),
        # sous-tâche 2 (sans tool)
        Phase1FilteredEvent(session_id=SID, task_id=S2, agent_id="ag", passed=True, fit_score=0.9),
        DispatchedEvent(session_id=SID, task_id=S2, agent_id="ag", reason="sole claimer"),
        ExecutedEvent(session_id=SID, task_id=S2, agent_id="ag", output_summary="s2", output_content="c2"),
        QAEvaluatedEvent(session_id=SID, task_id=S2, agent_id="ag", success=True, score=1.0, reason="r"),
        TaskAggregatedEvent(session_id=SID, task_id=P, sub_task_ids=[S1, S2], output_summary="final", output_content="final report"),
    ]


class TestDividedRunMilestones:
    def test_milestone_sequence(self):
        graph = build_graph(_divided_events(), _divided_meta("parent", "incident"))
        types = [s.milestone_type for s in graph.steps]
        assert types == [
            "input", "divider",
            "dispatch", "tool", "agent", "evaluator",   # sub1
            "dispatch", "agent", "evaluator",            # sub2 (pas de tool)
            "aggregator", "output",
        ]

    def test_divider_milestone_lists_sub_tasks(self):
        graph = build_graph(_divided_events(), _divided_meta("parent", "incident"))
        div = next(s for s in graph.steps if s.milestone_type == "divider")
        assert "divider" in div.active_nodes
        assert [st.id for st in div.detail.divider.sub_tasks] == ["sub1", "sub2"]
        pairs = {(e.from_node, e.to) for e in div.active_edges}
        assert ("input", "divider") in pairs

    def test_dispatch_backbone_divider_to_dispatch(self):
        graph = build_graph(_divided_events(), _divided_meta("parent", "incident"))
        first_disp = next(s for s in graph.steps if s.milestone_type == "dispatch")
        pairs = {(e.from_node, e.to) for e in first_disp.active_edges}
        assert ("divider", "dispatch") in pairs

    def test_subtask_detail_scoped(self):
        graph = build_graph(_divided_events(), _divided_meta("parent", "incident"))
        agent_steps = [s for s in graph.steps if s.milestone_type == "agent"]
        assert agent_steps[0].detail.agents["ag"].output_content == "c1"
        assert agent_steps[1].detail.agents["ag"].output_content == "c2"
        assert agent_steps[0].sub_task_id == "sub1"
        assert agent_steps[1].sub_task_id == "sub2"

    def test_aggregator_and_output(self):
        graph = build_graph(_divided_events(), _divided_meta("parent", "incident"))
        agg = next(s for s in graph.steps if s.milestone_type == "aggregator")
        assert agg.detail.aggregator.sub_task_ids == ["sub1", "sub2"]
        pairs = {(e.from_node, e.to) for e in agg.active_edges}
        assert ("evaluator", "aggregator") in pairs
        out = graph.steps[-1]
        assert out.milestone_type == "output"
        assert out.detail.output.output_content == "final report"
        out_pairs = {(e.from_node, e.to) for e in out.active_edges}
        assert ("aggregator", "output") in out_pairs
```

- [ ] **Step 2: Lancer, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_build_graph_milestones.py::TestDividedRunMilestones -v`
Expected: FAIL (`_milestones_divided` non défini → NameError dans `build_graph`).

- [ ] **Step 3: Implémenter `_milestones_divided`**

Ajouter dans `dashboard/graph_model.py` :

```python
def _milestones_divided(divided_ev, aggregated_ev, sub_runs, parent_record, parent_id) -> list[GraphStep]:
    parent_input = _make_input_detail(parent_record, parent_id)
    acc = _EdgeAccumulator()
    steps: list[GraphStep] = []

    # INPUT (parent)
    parent_detail = StepDetail(input=parent_input)
    steps.append(GraphStep(milestone_type="input", label="INPUT", active_nodes=["input"],
                           active_edges=acc.snapshot([]), outcome="divided", detail=parent_detail,
                           todo=_todo_divided(divided_ev, sub_runs, "input", None)))

    # DIVIDER
    acc.add_backbone("input", "divider")
    div_detail = StepDetail(input=parent_input, divider=DividerDetail(
        divided=True,
        sub_tasks=[DividerSubTaskInfo(id=st.id, description=st.description, depends_on=list(st.depends_on)) for st in divided_ev.sub_tasks],
    ))
    steps.append(GraphStep(milestone_type="divider", label="DIVIDER", active_nodes=["divider"],
                           active_edges=acc.snapshot([]), outcome="divided", detail=div_detail,
                           todo=_todo_divided(divided_ev, sub_runs, "divider", None)))

    # Sous-tâches dans l'ordre d'émission (= ordre topologique de run_chain)
    for idx, run in enumerate(sub_runs):
        sub_input = InputDetail(task_id=run.task_id, description=_sub_desc(divided_ev, run.task_id))
        detail = _scope_detail(sub_input, run)
        winner = run.winner_id

        acc.add_backbone("divider", "dispatch")
        fan = [("dispatch", winner)] if winner else []
        nodes_active = ["dispatch"] + ([winner] if winner else [])
        steps.append(GraphStep(milestone_type="dispatch", label=f"DISPATCH · {idx + 1}", sub_task_id=run.task_id,
                               order_index=idx, active_nodes=nodes_active, active_edges=acc.snapshot(fan),
                               winner_agent_id=winner, outcome=run.outcome, detail=detail,
                               todo=_todo_divided(divided_ev, sub_runs, "dispatch", run.task_id)))
        if winner is None:
            continue

        for ts in _tool_milestones(run, detail, acc, run.task_id):
            ts.order_index = idx
            ts.todo = _todo_divided(divided_ev, sub_runs, "tool", run.task_id)
            steps.append(ts)

        steps.append(GraphStep(milestone_type="agent", label=f"AGENT · {winner}", sub_task_id=run.task_id,
                               order_index=idx, active_nodes=[winner], active_edges=acc.snapshot([("dispatch", winner)]),
                               winner_agent_id=winner, outcome=run.outcome, detail=detail,
                               todo=_todo_divided(divided_ev, sub_runs, "agent", run.task_id)))

        if run.qa is not None:
            fanq = [("dispatch", winner), (winner, "evaluator")]
            nodes_q = ["evaluator"]
            if run.outcome == "qa_fail":
                fanq.append(("evaluator", "testset"))
                nodes_q.append("testset")
            steps.append(GraphStep(milestone_type="evaluator", label=f"EVALUATOR · {idx + 1}", sub_task_id=run.task_id,
                                   order_index=idx, active_nodes=nodes_q, active_edges=acc.snapshot(fanq),
                                   winner_agent_id=winner, outcome=run.outcome, detail=detail,
                                   todo=_todo_divided(divided_ev, sub_runs, "evaluator", run.task_id)))

    # AGGREGATOR
    if aggregated_ev is not None:
        acc.add_backbone("evaluator", "aggregator")
        agg_detail = StepDetail(input=parent_input, aggregator=AggregatorDetail(
            aggregated=True, sub_task_ids=list(aggregated_ev.sub_task_ids),
            output_summary=aggregated_ev.output_summary, output_content=aggregated_ev.output_content,
        ))
        agg_detail.output = OutputDetail(produced=True, output_summary=aggregated_ev.output_summary,
                                         output_content=aggregated_ev.output_content, llm_metadata=aggregated_ev.llm_metadata)
        steps.append(GraphStep(milestone_type="aggregator", label="AGGREGATOR", active_nodes=["aggregator"],
                               active_edges=acc.snapshot([]), outcome="divided", detail=agg_detail,
                               todo=_todo_divided(divided_ev, sub_runs, "aggregator", None)))

        # OUTPUT
        acc.add_backbone("aggregator", "output")
        steps.append(GraphStep(milestone_type="output", label="OUTPUT", active_nodes=["output"],
                               active_edges=acc.snapshot([]), outcome="divided", detail=agg_detail,
                               todo=_todo_divided(divided_ev, sub_runs, "output", None)))
    return steps


def _sub_desc(divided_ev, task_id: str) -> str:
    for st in divided_ev.sub_tasks:
        if st.id == task_id:
            return st.description
    return task_id
```

Ajouter le stub TODO divisé (remplacé en Task 6) :

```python
def _todo_divided(divided_ev, sub_runs, milestone, current_task_id):  # remplacé en Task 6
    return []
```

- [ ] **Step 4: Lancer, vérifier le PASS**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_build_graph_milestones.py::TestDividedRunMilestones -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Réécrire `tests/dashboard/test_build_graph_a4.py` vers le modèle jalons**

Remplacer son contenu par :

```python
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
        assert "divider" in ids and "aggregator" in ids

    def test_divided_milestone_sequence(self):
        types = [s.milestone_type for s in build_graph(_divided_events(), _meta()).steps]
        assert types == ["input", "divider", "dispatch", "agent", "evaluator", "aggregator", "output"]

    def test_output_carries_aggregated_content(self):
        out = build_graph(_divided_events(), _meta()).steps[-1]
        assert out.detail.output.output_content == "synthesized"
```

- [ ] **Step 6: Lancer toute la suite graph, vérifier le PASS**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_build_graph_a4.py tests/dashboard/test_build_graph_milestones.py -v`
Expected: PASS (les tests TODO échouent encore — activés en Task 6).

- [ ] **Step 7: Commit**

```bash
git add dashboard/graph_model.py tests/dashboard/test_build_graph_a4.py tests/dashboard/test_build_graph_milestones.py
git commit -m "feat(v2-frontend): jalons run divisé (divider, sous-tâches topo, aggregator)"
```

---

### Task 6: Builder — TODO snapshot par jalon

La TODO évolue : à INPUT elle ne contient que la racine ; au DIVIDER les sous-tâches apparaissent (pending) ; au DISPATCH d'une sous-tâche elle devient `current` ; à son EVALUATOR elle devient `done` (pass) ou `failed` (fail).

**Files:**
- Modify: `dashboard/graph_model.py` (`_todo_simple`, `_todo_divided`)
- Test: `tests/dashboard/test_build_graph_milestones.py`

- [ ] **Step 1: Écrire les tests TODO**

Ajouter à `tests/dashboard/test_build_graph_milestones.py` :

```python
class TestTodoSimple:
    def test_root_only_and_done_at_output(self):
        graph = build_graph(_simple_run(), _meta("t1", "do it"))
        first = graph.steps[0].todo
        assert len(first) == 1 and first[0].is_root and first[0].state == "current"
        last = graph.steps[-1].todo
        assert last[0].state == "done"

    def test_root_failed_on_qa_fail(self):
        graph = build_graph(_simple_run(success=False), _meta("t1", "do it"))
        ev = next(s for s in graph.steps if s.milestone_type == "evaluator")
        assert ev.todo[0].state == "failed"


class TestTodoDivided:
    def test_subtasks_appear_at_divider(self):
        graph = build_graph(_divided_events(), _divided_meta("parent", "incident"))
        inp = graph.steps[0].todo
        assert len(inp) == 1 and inp[0].is_root
        div = next(s for s in graph.steps if s.milestone_type == "divider").todo
        assert {t.id for t in div if not t.is_root} == {"sub1", "sub2"}
        assert all(t.state == "pending" for t in div if not t.is_root)

    def test_subtask_current_then_done(self):
        graph = build_graph(_divided_events(), _divided_meta("parent", "incident"))
        # au dispatch de sub1, sub1 = current, sub2 = pending
        disp1 = next(s for s in graph.steps if s.milestone_type == "dispatch" and s.sub_task_id == "sub1")
        states = {t.id: t.state for t in disp1.todo if not t.is_root}
        assert states == {"sub1": "current", "sub2": "pending"}
        # à l'output, les deux sont done
        out = graph.steps[-1].todo
        done = {t.id: t.state for t in out if not t.is_root}
        assert done == {"sub1": "done", "sub2": "done"}
```

- [ ] **Step 2: Lancer, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_build_graph_milestones.py::TestTodoSimple tests/dashboard/test_build_graph_milestones.py::TestTodoDivided -v`
Expected: FAIL (stubs renvoient `[]`).

- [ ] **Step 3: Implémenter les TODO**

Remplacer les stubs `_todo_simple` et `_todo_divided` par :

```python
def _root_state(milestone: str) -> Literal["current", "done"]:
    return "done" if milestone == "output" else "current"


def _todo_simple(record, tid, milestone, run) -> list[TodoItem]:
    desc = record.description if record is not None else tid
    if run is not None and milestone == "evaluator" and run.outcome == "qa_fail":
        state: Literal["pending", "current", "done", "failed"] = "failed"
    else:
        state = _root_state(milestone)
    return [TodoItem(id=tid, description=desc, state=state, is_root=True)]


def _sub_state(run: "_SubTaskRun", milestone: str, current_task_id: str | None) -> Literal["pending", "current", "done", "failed"]:
    """État d'une sous-tâche au jalon courant.

    resolved (done/failed) si son EVALUATOR est déjà passé ;
    current si on est sur un de ses jalons (dispatch/tool/agent/evaluator) ;
    pending sinon.
    """
    raise NotImplementedError  # remplacé inline ci-dessous


def _todo_divided(divided_ev, sub_runs, milestone, current_task_id) -> list[TodoItem]:
    # racine
    items = [TodoItem(id=divided_ev.task_id, description="(input)", state=_root_state(milestone), is_root=True)]
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
```

Supprimer le `def _sub_state(...)` (laissé par erreur ci-dessus) : il n'est pas utilisé, retirer ce stub `NotImplementedError` avant de lancer les tests.

- [ ] **Step 4: Lancer, vérifier le PASS**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_build_graph_milestones.py -v`
Expected: PASS (toute la suite milestones).

- [ ] **Step 5: Test d'intégration sur la trace réelle (si présente)**

Ajouter à `tests/dashboard/test_build_graph_milestones.py` (skip si la trace gitignored est absente) :

```python
import pytest
from pathlib import Path
from aaosa.tracing.store import load_trace

_REAL = Path("runs/sessions/2026-06-02T09-24-21-12a72561")


@pytest.mark.skipif(not (_REAL / "trace.jsonl").exists(), reason="trace réelle gitignored absente")
class TestRealDividedTrace:
    def test_real_trace_milestone_shape(self):
        from aaosa.tracing.store import SessionMeta
        events = load_trace(_REAL / "trace.jsonl")
        meta = SessionMeta.model_validate_json((_REAL / "meta.json").read_text(encoding="utf-8"))
        graph = build_graph(events, meta)
        types = [s.milestone_type for s in graph.steps]
        assert types[0] == "input" and types[1] == "divider"
        assert types[-1] == "output" and types[-2] == "aggregator"
        assert types.count("evaluator") == 6     # 6 sous-tâches
        assert "tool" in types
        # tools RLE : moins de jalons tool que d'appels bruts (16 appels)
        n_tool_calls = sum(1 for e in events if e.type == "tool_called")
        assert sum(1 for t in types if t == "tool") < n_tool_calls
```

- [ ] **Step 6: Lancer, vérifier PASS (ou skip)**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_build_graph_milestones.py::TestRealDividedTrace -v`
Expected: PASS si la trace existe localement, sinon SKIPPED.

- [ ] **Step 7: Commit**

```bash
git add dashboard/graph_model.py tests/dashboard/test_build_graph_milestones.py
git commit -m "feat(v2-frontend): TODO snapshot par jalon (run simple + divisé) + test trace réelle"
```

---

### Task 7: États QA-fail et unassigned (run divisé)

**Files:**
- Test: `tests/dashboard/test_build_graph_milestones.py`

- [ ] **Step 1: Écrire les tests d'états**

Ajouter à `tests/dashboard/test_build_graph_milestones.py` :

```python
class TestFailAndUnassignedStates:
    def test_subtask_qa_fail_lights_testset_and_marks_todo(self):
        P, S1 = "p", "s1"
        events = [
            TaskDividedEvent(session_id=SID, task_id=P, sub_tasks=[DividedSubTask(id=S1, description="x", depends_on=[])]),
            Phase1FilteredEvent(session_id=SID, task_id=S1, agent_id="ag", passed=True, fit_score=0.9),
            DispatchedEvent(session_id=SID, task_id=S1, agent_id="ag", reason="sole claimer"),
            ExecutedEvent(session_id=SID, task_id=S1, agent_id="ag", output_summary="s", output_content="c"),
            QAEvaluatedEvent(session_id=SID, task_id=S1, agent_id="ag", success=False, score=0.0, reason="bad"),
            TaskAggregatedEvent(session_id=SID, task_id=P, sub_task_ids=[S1], output_summary="f", output_content="f"),
        ]
        graph = build_graph(events, _divided_meta("p", "x"))
        ev = next(s for s in graph.steps if s.milestone_type == "evaluator")
        assert ev.outcome == "qa_fail"
        assert "testset" in ev.active_nodes
        assert {(e.from_node, e.to) for e in ev.active_edges} >= {("evaluator", "testset")}
        sub_item = next(t for t in ev.todo if not t.is_root)
        assert sub_item.state == "failed"

    def test_subtask_unassigned_stops_at_dispatch(self):
        P, S1 = "p", "s1"
        events = [
            TaskDividedEvent(session_id=SID, task_id=P, sub_tasks=[DividedSubTask(id=S1, description="x", depends_on=[])]),
            Phase1FilteredEvent(session_id=SID, task_id=S1, agent_id="ag", passed=False, fit_score=0.0),
            UnassignedEvent(session_id=SID, task_id=S1, reason="no agent"),
            TaskAggregatedEvent(session_id=SID, task_id=P, sub_task_ids=[], output_summary="f", output_content="f"),
        ]
        graph = build_graph(events, _divided_meta("p", "x"))
        sub_types = [s.milestone_type for s in graph.steps if s.sub_task_id == S1]
        assert sub_types == ["dispatch"]   # pas d'agent/evaluator
        disp = next(s for s in graph.steps if s.milestone_type == "dispatch")
        assert disp.winner_agent_id is None
        assert disp.detail.dispatch.unassigned_reason == "no agent"
```

- [ ] **Step 2: Lancer, vérifier le résultat**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_build_graph_milestones.py::TestFailAndUnassignedStates -v`
Expected: PASS (la logique est déjà en place via `run.outcome` ; ce test verrouille le comportement). Si un test échoue, corriger `_milestones_divided`/`_scope_detail` jusqu'au PASS (ex : s'assurer que `continue` saute bien agent/evaluator quand `winner is None`).

- [ ] **Step 3: Commit**

```bash
git add tests/dashboard/test_build_graph_milestones.py
git commit -m "test(v2-frontend): verrou états qa_fail + unassigned (run divisé)"
```

---

### Task 8: Intégration collectors + sérialisation

**Files:**
- Verify: `dashboard/collectors/sessions.py`, `dashboard/collectors/health_checks.py`
- Modify: `tests/dashboard/test_serialization.py` (étendre)
- Test: `tests/dashboard/test_collectors_sessions.py`, `tests/dashboard/test_collectors_health_checks.py`

- [ ] **Step 1: Lancer les suites collectors existantes**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_collectors_sessions.py tests/dashboard/test_collectors_health_checks.py -v`
Expected: certains tests échouent s'ils asseyaient l'ancien modèle `GraphStep` (champs `task_id`/`active_nodes` per-tâche). Lire les échecs.

- [ ] **Step 2: Adapter les assertions collectors au modèle jalons**

Dans `tests/dashboard/test_collectors_sessions.py` et `test_collectors_health_checks.py`, remplacer toute assertion sur `graph.steps[i].task_id` ou sur la forme per-tâche par des assertions sur `milestone_type`. Exemple type pour sessions (adapter aux fixtures réelles du fichier) :

```python
def test_session_detail_graph_is_milestone_based(view):
    types = [s.milestone_type for s in view.graph.steps]
    assert types[0] == "input"
    assert "dispatch" in types
```

Pour health (`case_graph` single-task) : vérifier que la séquence est `["input", "dispatch", ...]` et se termine par `"output"` (ou `"evaluator"` si pas d'output produit). Garder le `skipif`/fixtures existants.

- [ ] **Step 3: Étendre `test_serialization.py`**

Ajouter un test qui vérifie que le nouveau `GraphModel` (avec tools + divider/aggregator/tool details + todo) sérialise en JSON avec l'alias `from` préservé et `tool_calls_count` présent dans `llm_metadata` :

```python
def test_divided_graph_serializes_with_aliases():
    from tests.dashboard.test_build_graph_milestones import _divided_events, _divided_meta
    from dashboard.graph_model import build_graph
    graph = build_graph(_divided_events(), _divided_meta("parent", "incident"))
    dumped = graph.model_dump(by_alias=True, mode="json")
    # arêtes : alias 'from'
    assert all("from" in e for e in dumped["edges"])
    # un jalon tool porte son détail
    tool_step = next(s for s in dumped["steps"] if s["milestone_type"] == "tool")
    assert tool_step["detail"]["tool"]["tool_name"] == "grep"
    # todo présent sur chaque jalon
    assert all("todo" in s for s in dumped["steps"])
```

- [ ] **Step 4: Lancer toute la suite dashboard**

Run: `.venv\Scripts\python -m pytest tests/dashboard/ -v`
Expected: PASS (toute la suite dashboard verte).

- [ ] **Step 5: Lancer la suite complète (non-régression V2c/V3)**

Run: `.venv\Scripts\python -m pytest -q`
Expected: PASS — le nombre total de tests a augmenté vs 690 ; aucun test hors `tests/dashboard/` ne régresse (les events/schémas vague 1 sont intouchés).

- [ ] **Step 6: Commit**

```bash
git add dashboard/collectors tests/dashboard/test_serialization.py tests/dashboard/test_collectors_sessions.py tests/dashboard/test_collectors_health_checks.py
git commit -m "test(v2-frontend): collectors + sérialisation alignés sur le modèle jalons"
```

---

## PARTIE B — Frontend (validé navigateur, hors TDD auto)

Conforme à V2c : le JS n'a pas de tests auto ; validation = navigateur sur le run réel. Respecter `DESIGN.md`/`PRODUCT.md` (instrument wireframe, ember = actif/winner seul, pas de néon multi-hue, pas de glass).

### Task 9: graph.js — 4 bandes + tier tools + allumage cumulatif

**Files:**
- Modify: `dashboard/static/js/graph.js`

- [ ] **Step 1: Passer à 4 bandes et ajouter le tier tools**

Remplacer les constantes de bandes (lignes 3-10) par :

```javascript
const LAYERS = ["tools", "bottom", "center", "top"];

// Anatomie « arbre » : tools = canopée (le plus haut), agents = feuilles, logique = tronc,
// in/out = racines (le plus bas). Ordre vertical visuel top→bottom.
const TIER_LABEL = {
  tools: "tools · capabilities",
  bottom: "leaves · agents",
  center: "trunk · logic",
  top: "roots · in/out",
};
```

Remplacer `layout(graph)` (lignes 20-43) par une version 4 bandes :

```javascript
function layout(graph) {
  const byLayer = { tools: [], bottom: [], center: [], top: [] };
  for (const n of graph.nodes) byLayer[n.layer].push(n);
  const maxCount = Math.max(1, ...LAYERS.map(l => byLayer[l].length));
  const width = PAD * 2 + maxCount * NODE_W + (maxCount - 1) * GAP_X;
  const height = PAD * 2 + 4 * NODE_H + 3 * BAND_GAP;
  // bandes empilées top→bottom : tools, bottom(agents), center(logic), top(io)
  const bandTop = {};
  LAYERS.forEach((l, i) => { bandTop[l] = PAD + i * (NODE_H + BAND_GAP); });
  const pos = {};
  for (const layer of LAYERS) {
    const row = byLayer[layer];
    const rowW = row.length * NODE_W + Math.max(0, row.length - 1) * GAP_X;
    const startX = (width - rowW) / 2;
    row.forEach((n, i) => {
      pos[n.id] = { cx: startX + i * (NODE_W + GAP_X) + NODE_W / 2, cy: bandTop[layer] + NODE_H / 2 };
    });
  }
  const tierY = Object.fromEntries(LAYERS.map(l => [l, bandTop[l] + NODE_H / 2]));
  return { pos, width, height, tierY };
}
```

- [ ] **Step 2: Vérifier le rendu des arêtes/nœuds cumulatifs**

Le corps de `renderGraph` (lignes 47-119) lit déjà `step.active_nodes`, `step.active_edges`, `step.winner_agent_id`, `step.outcome === "qa_fail"`. Comme le nouveau `GraphStep` conserve ces champs, **aucun changement de logique d'allumage n'est nécessaire**. Vérifier que le marqueur de tier itère sur les 4 `LAYERS` (la boucle `for (const layer of LAYERS)` lignes 62-66 le fait automatiquement). Ajouter un fallback de label pour les nœuds tool : ils utilisent déjà `n.label` (le `tool_name`), OK.

- [ ] **Step 3: Lancer le dashboard et valider visuellement**

Run: `.venv\Scripts\python -m dashboard` → http://localhost:5000, tab Sessions, sélectionner la session divisée `2026-06-02T09-24-21-12a72561`.
Expected : 4 bandes empilées ; la canopée `tools · capabilities` affiche 4 hexes (grep_codebase, read_file, explain_query_plan, run_tests) en idle ; le scrubber parcourt les jalons ; au jalon TOOL le lien agent→tool s'allume.

- [ ] **Step 4: Commit**

```bash
git add dashboard/static/js/graph.js
git commit -m "feat(v2-frontend): graphe 4 bandes + canopée tools + allumage cumulatif"
```

---

### Task 10: modal.js — modals divider/aggregator/tool + spec evaluator + tool_calls_count

**Files:**
- Modify: `dashboard/static/js/modal.js`

- [ ] **Step 1: Ajouter les renderers divider/aggregator/tool**

Ajouter avant `openNodeModal` :

```javascript
function renderDivider(d) {
  const f = document.createDocumentFragment();
  if (!d.divided) { f.append(field("Divider", "non déclenché")); return f; }
  d.sub_tasks.forEach((st, i) => {
    const deps = st.depends_on.length ? ` (dépend de ${st.depends_on.length})` : "";
    f.append(longField(`Sous-tâche ${i + 1}${deps}`, st.description));
  });
  return f;
}

function renderAggregator(a) {
  const f = document.createDocumentFragment();
  if (!a.aggregated) { f.append(field("Aggregator", "non exécuté")); return f; }
  f.append(field("Sous-tâches agrégées", String(a.sub_task_ids.length)));
  if (a.output_summary) f.append(longField("Résumé", a.output_summary));
  if (a.output_content) f.append(longField("Output synthétisé", a.output_content));
  return f;
}

function renderTool(t) {
  const f = document.createDocumentFragment();
  if (!t) { f.append(field("Tool", "non actif à cette étape")); return f; }
  f.append(field("Tool", t.tool_name + (t.calls.length > 1 ? ` ×${t.calls.length}` : "")));
  t.calls.forEach((c, i) => {
    f.append(field(`Appel ${i + 1} · args`, JSON.stringify(c.arguments)));
    f.append(longField(`Appel ${i + 1} · résultat`, c.result));
    f.append(field(`Appel ${i + 1} · latence`, `${c.latency_ms} ms`));
  });
  return f;
}
```

- [ ] **Step 2: Étendre `renderEvaluator` pour la spec générée**

Remplacer `renderEvaluator` (lignes 102-111) par :

```javascript
function renderEvaluator(e) {
  const f = document.createDocumentFragment();
  if (!e.ran) { f.append(field("Evaluator", "non exécuté")); return f; }
  f.append(field("Résultat", (e.success ? "succès" : "échec") + (e.score != null ? ` · score ${e.score.toFixed(2)}` : "")));
  const critLines = Object.entries(e.criteria_results || {}).map(([k, v]) => `${k} : ${v ? "✓" : "✗"}`);
  if (critLines.length) f.append(fieldLines("Critères / gates", critLines));
  if (e.judge) f.append(field("Judge", `${e.judge.mode} · ${e.judge.overall != null ? e.judge.overall.toFixed(2) : "—"}`));
  if (e.spec) {
    const specLines = e.spec.criteria.map(c => `${c.name}${c.gate ? " [gate]" : ""} · poids ${c.weight}` + (c.params && Object.keys(c.params).length ? ` · ${JSON.stringify(c.params)}` : ""));
    f.append(fieldLines("Spec générée (critères)", specLines.length ? specLines : ["—"]));
    f.append(field("Seuil de succès", String(e.spec.success_threshold)));
    if (e.spec.judge) f.append(field("Judge spec", `${e.spec.judge.mode} · poids ${e.spec.judge.weight}`));
  }
  if (e.reason) f.append(longField("Raison", e.reason));
  return f;
}
```

- [ ] **Step 3: Afficher tool_calls_count dans renderAgent**

Dans `renderAgent` (lignes 92-95), remplacer le bloc métriques par :

```javascript
  if (a.llm_metadata) {
    const m = a.llm_metadata;
    const tc = m.tool_calls_count != null ? ` · ${m.tool_calls_count} tool calls` : "";
    f.append(field("Métriques", `latence ${m.latency_ms} ms · in ${m.tokens_in} · out ${m.tokens_out}${tc}`));
  }
  if (a.tool_calls && a.tool_calls.length) {
    const lines = a.tool_calls.map(c => `${c.tool_name} (${c.latency_ms} ms)`);
    f.append(fieldLines("Appels d'outils", lines));
  }
```

- [ ] **Step 4: Brancher les nouveaux types dans `openNodeModal`**

Dans le `switch (node.type)` (lignes 146-159), ajouter avant `default` :

```javascript
    case "divider": body = renderDivider(step.detail.divider); break;
    case "aggregator": body = renderAggregator(step.detail.aggregator); break;
    case "tool": body = renderTool(step.detail.tool); break;
```

- [ ] **Step 5: Valider navigateur**

Run: dashboard ouvert (Task 9). Cliquer chaque nœud sur la session divisée : divider (liste 6 sous-tâches + deps), un agent (output + tool calls + métriques avec tool_calls_count), evaluator (spec générée + critères), aggregator (output synthétisé), un tool (args/résultat/latence par appel).
Expected : chaque modal s'ouvre avec le bon contenu, aucun crash console.

- [ ] **Step 6: Commit**

```bash
git add dashboard/static/js/modal.js
git commit -m "feat(v2-frontend): modals divider/aggregator/tool + spec evaluator + tool_calls_count"
```

---

### Task 11: sessions.js — TODO snapshot + labels scrubber par jalon

**Files:**
- Modify: `dashboard/static/js/tabs/sessions.js`

- [ ] **Step 1: Rendre la TODO depuis le snapshot du jalon courant**

Remplacer `renderTodo` (lignes 47-53) par :

```javascript
  function renderTodo() {
    const step = graph.steps[activeStepIndex];
    const items = step ? step.todo : [];
    todo.innerHTML = items.map(t => {
      const indent = t.is_root ? "" : " todo--sub";
      return `<div class="todo-item todo--${t.state}${indent}"><span class="mk"></span><span>${esc(t.description)}</span></div>`;
    }).join("");
  }
```

- [ ] **Step 2: Labels scrubber par jalon**

Dans `rerender` (lignes 59-71), le label utilise déjà `step.label` (qui vaut maintenant `INPUT`/`DIVIDER`/`DISPATCH · 1`/`TOOL · grep`/...). Remplacer la ligne du label par une version qui montre le type de jalon :

```javascript
      scrubLabel.innerHTML = `Jalon <b>${activeStepIndex + 1}</b> / ${n} — <span class="mono">${esc(step.label)}</span>`;
```

- [ ] **Step 3: Chips (compteur tasks/agents) restent valides**

`renderChips` lit `detail.meta.tasks.length` (le parent = 1) et `detail.meta.agent_ids.length`. Pour un run divisé, afficher aussi le nombre de sous-tâches issu du divider. Remplacer `renderChips` par :

```javascript
  function renderChips() {
    const subCount = (() => {
      const div = graph.steps.find(s => s.milestone_type === "divider");
      return div ? div.detail.divider.sub_tasks.length : 0;
    })();
    const sub = subCount ? `<span><b>${subCount}</b> sous-tâches</span>` : "";
    chips.innerHTML = `<span><b>${detail.meta.tasks.length}</b> tasks</span>${sub}<span><b>${detail.meta.agent_ids.length}</b> agents</span>`;
  }
```

- [ ] **Step 4: Valider navigateur**

Run: dashboard ouvert. Sur la session divisée : au premier jalon la TODO ne montre que l'input ; au DIVIDER les 6 sous-tâches apparaissent (pending) ; en avançant, la sous-tâche courante passe `current` puis `done` (rayée) ; le label scrubber affiche le type de jalon.
Expected : TODO vivante cohérente avec le scrub, chips montrent 1 task / 6 sous-tâches / N agents.

- [ ] **Step 5: Commit**

```bash
git add dashboard/static/js/tabs/sessions.js
git commit -m "feat(v2-frontend): TODO vivante par jalon + labels scrubber"
```

---

### Task 12: CSS — bande tools, sous-items TODO, champs modals

**Files:**
- Modify: `dashboard/static/css/` (le(s) fichier(s) existant(s) ; repérer celui qui porte `.todo-item`, `.node--*`, `.gtier`)

- [ ] **Step 1: Repérer le CSS courant**

Run: `.venv\Scripts\python -c "import pathlib; print([p.name for p in pathlib.Path('dashboard/static/css').glob('*.css')])"`
Lire le fichier qui contient `.todo-item` et `.node--agent` pour suivre les tokens (variables OKLCH `--fire`, graphite, mono) du système verrouillé.

- [ ] **Step 2: Styliser le nœud tool + l'état failed + sous-items TODO**

Ajouter (en réutilisant les tokens existants, sans introduire de nouvelle teinte) :

```css
/* tier tools : canopée idle, même langage que les autres nœuds wireframe */
.node--tool .hex { stroke-dasharray: 3 3; opacity: 0.7; }
.node--tool.node--active .hex { stroke-dasharray: none; opacity: 1; }

/* TODO : sous-items indentés + état failed */
.todo--sub { margin-left: 14px; }
.todo--failed { /* réutiliser la teinte d'échec existante (edge--fail) ; ne pas inventer de rouge néon */ }
.todo--failed .mk { /* marqueur d'échec, cohérent avec le style done/current */ }

/* labels scrubber mono */
.scrub-label .mono { font-family: var(--mono, monospace); letter-spacing: 0.02em; }
```

Pour `.todo--failed`, reprendre la couleur de `.edge--fail` (déjà définie) plutôt qu'un nouveau token. Pour `.todo--done` (rayé), vérifier que le style existant (text-decoration: line-through ou opacité) s'applique ; sinon l'ajouter.

- [ ] **Step 3: Valider navigateur (responsive + lisibilité)**

Run: dashboard ouvert. Vérifier : canopée tools lisible et discrète (idle), nœud tool actif qui « brûle » comme les autres, sous-items TODO indentés, item failed distinct sans néon, labels mono. Tester le redimensionnement de la fenêtre (le SVG auto-fit via `viewBox` doit tenir).
Expected : cohérent avec l'instrument verrouillé, aucune régression visuelle sur les runs simples (sessions non divisées + health tab).

- [ ] **Step 4: Commit**

```bash
git add dashboard/static/css
git commit -m "feat(v2-frontend): styles canopée tools, sous-items TODO, labels jalons"
```

---

### Task 13: Validation end-to-end + non-régression health tab

**Files:** aucune modification ; validation.

- [ ] **Step 1: Régénérer un run divisé frais (optionnel si trace présente)**

Run: `.venv\Scripts\python src\aaosa\demo\run_demo_v3.py` (requiert `OPENAI_API_KEY`).
Expected : nouvelle session persistée dans `runs/sessions/`.

- [ ] **Step 2: Validation navigateur complète — tab Sessions**

Run: `.venv\Scripts\python -m dashboard` → tab Sessions.
Checklist :
- run divisé : séquence INPUT→DIVIDER→(par sous-tâche DISPATCH→TOOL*→AGENT→EVALUATOR)→AGGREGATOR→OUTPUT ;
- backbone (input→divider→dispatch ... evaluator→aggregator→output) reste allumé en avançant ;
- fan-out (dispatch→agent, agent→tool, agent→evaluator) transitoire : seul le courant est allumé ;
- TODO vivante ; modals OK (Task 10) ;
- un run simple (session non divisée si présente) : INPUT→DISPATCH→AGENT→EVALUATOR→OUTPUT, pas de bande tools si aucun tool.

- [ ] **Step 3: Non-régression health tab**

Run: dashboard, tab Health checks ; ouvrir un case-graph.
Expected : le `case_graph` (single-task) s'affiche en jalons (INPUT→DISPATCH→[TOOL]→AGENT→EVALUATOR→OUTPUT) sans divider/aggregator, sans crash. Si un health check existe avec des cas non graphables (quarantaine), ils restent non graphables (collector renvoie `None`).

- [ ] **Step 4: Suite de tests finale**

Run: `.venv\Scripts\python -m pytest -q`
Expected : PASS complet.

- [ ] **Step 5: Commit final + mise à jour CLAUDE.md**

Mettre à jour la section État courant de `CLAUDE.md` (racine projet) : ajouter une ligne « V3 — observabilité vague 2 (frontend) : graphe cumulatif par jalons, tier tools, TODO vivante, modals divider/aggregator/tool + spec ». Puis :

```bash
git add CLAUDE.md
git commit -m "docs(v3): vague 2 frontend — graphe cumulatif par jalons"
```

---

## Self-Review (couverture spec)

- **4e bande tools (canopée idle)** → Task 2 (nœuds), Task 9 (rendu), Task 12 (style). ✓
- **Modèle cumulatif par jalons** → Task 3 (moteur + accumulation), Task 5 (divisé). ✓
- **Ordre TOOL avant AGENT (correction étape 1)** → Task 4 + Task 5 (séquence verrouillée par test). ✓
- **RLE tools par nom (décision Quentin)** → Task 4. ✓
- **ELO plié dans EVALUATOR (correction étape 1)** → `_scope_detail`/`_evaluator_detail` (pas de jalon ELO). ✓
- **INPUT/OUTPUT synthétisés (correction étape 1)** → `_make_input_detail` + OUTPUT depuis aggregated/executed. ✓
- **Backbone persistant / fan-out transitoire (agent→evaluator = fan-out verrouillé)** → `_EdgeAccumulator` (backbone) vs `snapshot(fanout)`. ✓
- **TODO vivante (expand au divider, rayé au QA-pass, failed au QA-fail)** → Task 6 + Task 11. ✓
- **Modals divider/aggregator/tool + spec evaluator** → Task 10. ✓
- **build_graph partagé (impacte health case-graph)** → Task 8 (collectors), Task 13 (validation health). ✓
- **États qa_fail + unassigned sans échantillon réel → fixtures** → Task 7. ✓
- **Fallback aggregator non détectable** → hors périmètre, noté (pas de flag). ✓ (limitation assumée)
- **Pas de live mode, pas de B2/B3 journey** → différés, non touchés. ✓

## Limitations assumées (documentées)

- `AggregatorDetail` ne porte pas de flag `fallback` : la trace n'émet aucun signal distinguant l'agrégation LLM du fallback `successful[-1]`. À revoir seulement si la vague 1 ajoute un champ d'event dédié.
- Le test d'intégration sur trace réelle (Task 6 Step 5) est `skipif` : la trace est gitignored. Les fixtures synthétiques portent le contrat ; la trace réelle ne sert que de vérification de forme locale.
