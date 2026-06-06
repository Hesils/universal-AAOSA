# Démo phase 1 — Observabilité série D : arbre émergent bottom-up — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **Frontend (PARTIE C) :** chaque task frontend s'exécute sous le skill `/impeccable` (register product, système « wireframe instrument » verrouillé `DESIGN.md`/`PRODUCT.md`). Invoquer le skill AVANT d'ouvrir les fichiers JS/CSS de la task.

**Goal:** Rendre le run de récupération complet (D1 récursion + D3 diagnostic/routage + D4 spec v2) observable et rejouable dans le tab Sessions : `DiagnosedEvent` + ré-éval visible côté runtime, `build_graph` réécrit en arbre de tâches (nœuds namespacés par branche, passes retry, roster_gap, diagnostic, tagger), frontend arbre bottom-up (delta 45°, crest→fire, caméra zoom/pan/follow, TODO hiérarchique navigable).

**Architecture:** Un seul event ajouté (`DiagnosedEvent`) ; le reste de la chaîne D3 est inféré dans `build_graph` (passe retry = nouvelle séquence Phase1 après un `DiagnosedEvent` sur le même `task_id` ; origine d'une division = `UnassignedEvent` vs `DiagnosedEvent(task_spec)`). `build_graph` passe de « un run = une rangée de sous-tâches » à « un run = un arbre » : partition des events par `task_id` (fiable, remplace l'heuristique frontière Phase1), arbre reconstruit depuis TOUS les `TaskDividedEvent`, pipeline instancié par branche (`dispatch:<tid>`, `agent:<tid>:<aid>`, …), walk récursif unique (run simple = arbre dégénéré). Le contrat API graphe **casse** (IDs namespacés) : frontend réécrit, tests migrés, tab Health couvert par la non-régression.

**Tech Stack:** Python 3.14, Pydantic 2.13, pytest 9 (backend pur, TDD) ; vanilla JS + SVG (frontend, hors TDD auto, validé navigateur sous `/impeccable`).

---

## Contexte et références

- **Spec (design verrouillé, 14 décisions)** : `docs/superpowers/specs/2026-06-06-v3-demo-phase1-observabilite-serie-d-design.md`
- **Runtime série D** : `src/aaosa/runtime/runner.py` (`run_with_recovery`, `_route_diagnostic`, `_divide_and_recover`, `_retry_with_consignes`), `src/aaosa/qa/diagnostic.py` (pur — ne PAS y mettre d'émission)
- **Builder actuel** : `dashboard/graph_model.py` (755 lignes, modèle jalons vague 2) — réécrit en profondeur
- **Frontend actuel** : `dashboard/static/js/{graph.js, modal.js, tabs/sessions.js}` + CSS
- **Design system** : `DESIGN.md` / `PRODUCT.md` (racine) — amendé en Task 14 (`--crest` = arête de montée)
- **Plan de référence (format + patterns)** : `docs/superpowers/plans/2026-06-02-v3-observabilite-vague2-frontend.md`
- **Run réel de validation** : `.venv\Scripts\python src\aaosa\demo\run_demo_v3.py` (utilise déjà `run_recovery` + `save_session`)

## Périmètre verrouillé

- **Section 1 spec** : `DiagnosedEvent` (seul event ajouté, émis par le runner y compris sur échec LLM) + 2e `QAEvaluatedEvent` émis par le runner sur la ré-éval route evaluator. `diagnostic.py` reste pur.
- **Section 2 spec** : `build_graph` arbre — partition `task_id`, passes (`pass_index`), arbre récursif, nœuds namespacés, paire divider/aggregator par niveau, court-circuit single-sink sans aggregator, roster_gap, diagnostic, tagger inféré, `GraphEdge.flow`, TODO hiérarchique backend.
- **Section 3 spec** : frontend arbre bottom-up, delta 45°, crest→fire, caméra + follow-mode, TODO navigable, modals DIAG/ROSTER GAP/evaluator pass-aware, labels scrubber.
- **Hors scope** : live mode, multi-runs par session (1 run/graphe maintenu), phases 2-5 démo, `TaggedEvent` runtime.
- **Fallback documenté (spec §8)** : si l'arbre pur est illisible à l'implémentation → tier d'agents global. Épuiser d'abord : badge ×N + hover toutes-instances + compétition dans le modal DISPATCH. Décision Quentin au moment de la validation navigateur (Task 17), pas avant.

## Structure de fichiers

| Fichier | Responsabilité | Action |
| --- | --- | --- |
| `src/aaosa/tracing/events.py` | + `DiagnosedEvent` + union | Modifier |
| `src/aaosa/runtime/runner.py` | Émissions `_route_diagnostic` | Modifier |
| `tests/tracing/test_diagnosed_event.py` | Schéma + round-trip union | Créer |
| `tests/runtime/test_d3_events.py` | Émissions runner (4 routes + échec LLM + ré-éval) | Créer |
| `dashboard/graph_model.py` | Modèle étendu + builder arbre (réécriture) | Réécrire |
| `tests/dashboard/test_build_graph_tree.py` | Nouveau contrat arbre (partition, passes, D1/D3, roster_gap, tagger, TODO) | Créer |
| `tests/dashboard/test_graph_model.py` | Tests schéma (étendre nouveaux champs) | Modifier |
| `tests/dashboard/test_build_graph_milestones.py` | Migrer vers IDs namespacés | Modifier |
| `tests/dashboard/test_build_graph_a4.py` / `test_build_graph_d2.py` | Migrer vers IDs namespacés | Modifier |
| `tests/dashboard/test_serialization.py` | + `flow`, `tasks`, `pass_index` | Étendre |
| `dashboard/static/js/graph.js` | Layout arbre + routage delta 45° + flow colors + ×N | Réécrire |
| `dashboard/static/js/camera.js` | Zoom/pan/follow-mode (viewBox) | Créer |
| `dashboard/static/js/modal.js` | + DIAG, ROSTER GAP, TAGGER ; divider origine | Modifier |
| `dashboard/static/js/tabs/sessions.js` | TODO hiérarchique, follow, scrubber, stepForNode namespacé | Modifier |
| `dashboard/static/css/*.css` | Arêtes flow, nœuds diag/gap, TODO depth, bouton ⌖ | Modifier |
| `DESIGN.md` | Amendement : `--crest` = arête de montée | Modifier |
| `CLAUDE.md` | État courant | Modifier (Task 17) |

## Contrat cible du modèle (référence pour toutes les tasks)

```python
NodeLayer = Literal["tools", "bottom", "center", "top"]          # conservé pour l'API ; le layout frontend n'en dépend plus
NodeType = Literal["input", "tagger", "dispatch", "evaluator", "diagnostic", "roster_gap",
                   "output", "testset", "agent", "divider", "aggregator", "tool"]
MilestoneType = Literal["input", "tagger", "divider", "dispatch", "agent", "tool",
                        "evaluator", "diagnostic", "roster_gap", "aggregator", "output"]
Outcome = Literal["qa_pass", "qa_fail", "unassigned", "no_qa", "divided", "roster_gap", "diagnosed"]
EdgeFlow = Literal["ascent", "descent", "transient"]
```

**IDs de nœuds** : globaux `input`, `tagger`, `output` ; par branche `dispatch:<tid>`, `evaluator:<tid>`,
`diagnostic:<tid>`, `roster_gap:<tid>`, `divider:<tid>`, `aggregator:<tid>` ; composites
`agent:<tid>:<aid>`, `tool:<tid>:<name>`.

**Flows** : montée (`ascent`) = input→tagger→dispatch, divider→branches (bus d'émission), dispatch→agent,
X→divider (la division pousse un étage). Descente (`descent`) = agent→evaluator, evaluator→diagnostic,
descentes vers aggregator/output (bus de collecte). `transient` = agent→tool, deps inter-sœurs,
loop-backs du diagnostic (routes agent/evaluator).

**Décisions d'implémentation prises par ce plan** (dans le cadre de la spec, à mentionner à la review) :
1. `GraphModel.tasks: list[TaskBranch]` (id, parent_id, depth, order_index, description) — additif ;
   le frontend en a besoin pour le layout de l'arbre (la spec ne précisait pas le véhicule de la topologie).
2. `GraphNode.task_id` / `GraphNode.agent_id` — additifs ; portent l'appartenance de branche et
   l'« agent_id réel » exigé par la spec §4.3 pour le badge ×N.
3. `TodoItem.note: str | None` — additif ; porte les annotations de marge de la spec §5.5
   (« pass 2 », « roster gap », « route task_spec »).
4. **Le nœud `testset` disparaît du graphe** : absent de la liste de nœuds de la spec §4.3 (en série D,
   un qa_fail route vers DIAG, pas vers un fork). `TestSetDetail` reste dans `StepDetail` (API stable).
   À confirmer par Quentin en Task 17.
5. Agrégation fallback (`sinks[-1]`, exception aggregator, pas d'event) : indétectable depuis la trace —
   rendue comme un court-circuit depuis le dernier sink. Limitation déjà assumée vague 2.

---

## PARTIE A — Events et émissions runtime (TDD)

### Task 1: `DiagnosedEvent` — schéma + union

**Files:**
- Modify: `src/aaosa/tracing/events.py`
- Test: `tests/tracing/test_diagnosed_event.py` (créer)

- [ ] **Step 1: Écrire les tests de schéma**

Créer `tests/tracing/test_diagnosed_event.py` :

```python
import pytest
from pydantic import TypeAdapter, ValidationError

from aaosa.tracing.events import ClaimEvent, DiagnosedEvent


def test_diagnosed_event_minimal():
    e = DiagnosedEvent(session_id="s", task_id="t", attribution="agent", reason="weak answer")
    assert e.type == "diagnosed"
    assert e.agent_id is None
    assert e.consignes is None


def test_diagnosed_event_full():
    e = DiagnosedEvent(
        session_id="s", task_id="t", agent_id="ag-1",
        attribution="evaluator", reason="criteria too strict", consignes="relax min_length",
    )
    assert e.attribution == "evaluator"
    assert e.consignes == "relax min_length"


def test_diagnosed_event_rejects_unknown_attribution():
    with pytest.raises(ValidationError):
        DiagnosedEvent(session_id="s", task_id="t", attribution="cosmic_rays", reason="r")


def test_diagnosed_event_roundtrip_through_union():
    e = DiagnosedEvent(session_id="s", task_id="t", agent_id="ag-1",
                       attribution="task_spec", reason="ambiguous")
    adapter = TypeAdapter(ClaimEvent)
    parsed = adapter.validate_json(e.model_dump_json())
    assert isinstance(parsed, DiagnosedEvent)
    assert parsed.attribution == "task_spec"


def test_diagnosed_event_forbids_extra():
    with pytest.raises(ValidationError):
        DiagnosedEvent(session_id="s", task_id="t", attribution="agent", reason="r", extra_field="x")
```

- [ ] **Step 2: Lancer, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/tracing/test_diagnosed_event.py -v`
Expected: FAIL (ImportError `DiagnosedEvent`).

- [ ] **Step 3: Implémenter `DiagnosedEvent`**

Dans `src/aaosa/tracing/events.py`, ajouter après `TagLostEvent` (avant `RosterGapEvent`) :

```python
class DiagnosedEvent(_BaseEvent):
    type: Literal["diagnosed"] = "diagnosed"
    agent_id: str | None = None    # agent du failed output (None si inconnu)
    attribution: Literal["agent", "evaluator", "task_spec", "unattributed"]
    reason: str                    # raison du diagnostic ("" si échec LLM)
    consignes: str | None = None   # consignes de correction (routes agent/evaluator)
```

Et l'ajouter à l'union `ClaimEvent` (après `TagLostEvent,`) :

```python
        TagLostEvent,
        DiagnosedEvent,
        RosterGapEvent,
```

- [ ] **Step 4: Lancer, vérifier le PASS**

Run: `.venv\Scripts\python -m pytest tests/tracing/ -v`
Expected: PASS (les 5 nouveaux + aucun test tracing existant cassé).

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/tracing/events.py tests/tracing/test_diagnosed_event.py
git commit -m "feat(demo-p1): DiagnosedEvent — seul event ajouté de la chaîne D3"
```

---

### Task 2: Émissions runner — `DiagnosedEvent` + 2e `QAEvaluatedEvent` (ré-éval)

`_route_diagnostic` émet le `DiagnosedEvent` JUSTE après `diagnose_failure` (y compris quand il renvoie
`None` → `unattributed`, `reason=""`). Sur la branche `evaluator`, le runner émet un 2e `QAEvaluatedEvent`
portant `qa2` (avec `spec=qa2.spec_used` = la spec régénérée). Le pattern observer est préservé :
`diagnostic.py` n'est pas touché.

**Files:**
- Modify: `src/aaosa/runtime/runner.py` (`_route_diagnostic` + imports)
- Test: `tests/runtime/test_d3_events.py` (créer)

- [ ] **Step 1: Écrire les tests d'émission**

Créer `tests/runtime/test_d3_events.py` (réutilise les patterns de `tests/runtime/test_d3_routes.py`) :

```python
from types import SimpleNamespace

import aaosa.runtime.runner as runner
from aaosa.qa.diagnostic import DiagnosticResult
from aaosa.qa.protocol import QAFailure, QAResult
from aaosa.qa.spec import CriterionSpec, EvaluatorSpec
from aaosa.runtime.context import RunContext
from aaosa.schemas.output import LLMMetadata, Output
from aaosa.schemas.task import Task
from aaosa.tracing.events import DiagnosedEvent, QAEvaluatedEvent
from aaosa.tracing.tracer import Tracer


def _task() -> Task:
    return Task(description="do x", required_tags={"python": 50})


def _output(content="answer") -> Output:
    return Output(task_id="t", agent_id="a", content=content,
                  llm_metadata=LLMMetadata(model_name="m", tokens_in=1, tokens_out=1, latency_ms=1.0))


def _qa_fail() -> QAFailure:
    qa = QAResult(task_id="t", agent_id="a", success=False, score=0.2,
                  reason="too short", criteria_results={"min_length": False})
    return QAFailure(task_id="t", agent_id="a", output=_output("bad"), qa_result=qa)


class _StubAgentRoster:
    def __init__(self):
        self.tags_with_elo = {"python": 50}


def _ctx(tracer: Tracer) -> RunContext:
    return RunContext(
        agents=[_StubAgentRoster()], client=SimpleNamespace(), divider=SimpleNamespace(),
        aggregator=SimpleNamespace(), tagger=SimpleNamespace(), tracer=tracer, evaluator=None,
    )


def _diag_events(tracer):
    return [e for e in tracer.events if isinstance(e, DiagnosedEvent)]


def test_diagnosed_emitted_on_agent_route(monkeypatch):
    calls = [_qa_fail(), _output("good")]
    monkeypatch.setattr(runner, "run_task", lambda *a, **k: calls.pop(0))
    monkeypatch.setattr(runner, "diagnose_failure",
                        lambda *a, **k: DiagnosticResult(attribution="agent", consignes="be precise", reason="weak"))
    tracer = Tracer("s")
    runner.run_with_recovery(_task(), _ctx(tracer))
    diag = _diag_events(tracer)
    assert len(diag) == 1
    assert diag[0].attribution == "agent"
    assert diag[0].consignes == "be precise"
    assert diag[0].reason == "weak"
    assert diag[0].agent_id == "a"          # agent du failed output (QAFailure.agent_id)


def test_diagnosed_emitted_on_llm_failure_as_unattributed(monkeypatch):
    monkeypatch.setattr(runner, "run_task", lambda *a, **k: _qa_fail())
    monkeypatch.setattr(runner, "diagnose_failure", lambda *a, **k: None)
    tracer = Tracer("s")
    out = runner.run_with_recovery(_task(), _ctx(tracer))
    assert out.status == "qa_failed"
    diag = _diag_events(tracer)
    assert len(diag) == 1
    assert diag[0].attribution == "unattributed"
    assert diag[0].reason == ""
    assert diag[0].consignes is None


def test_diagnosed_emitted_on_task_spec_route(monkeypatch):
    # divider atomique → qa_failed(task_spec), mais le DiagnosedEvent est émis AVANT le routage
    monkeypatch.setattr(runner, "run_task", lambda *a, **k: _qa_fail())
    monkeypatch.setattr(runner, "diagnose_failure",
                        lambda *a, **k: DiagnosticResult(attribution="task_spec", reason="ambiguous"))

    class _AtomicDivider:
        def divide(self, task, client, chained_context=None, failure_context=None):
            from aaosa.runtime.divider import DivisionResult
            return DivisionResult(is_atomic=True)

    tracer = Tracer("s")
    ctx = RunContext(agents=[_StubAgentRoster()], client=SimpleNamespace(), divider=_AtomicDivider(),
                     aggregator=SimpleNamespace(), tagger=SimpleNamespace(), tracer=tracer, evaluator=None)
    runner.run_with_recovery(_task(), ctx)
    diag = _diag_events(tracer)
    assert len(diag) == 1
    assert diag[0].attribution == "task_spec"


def test_no_tracer_no_crash(monkeypatch):
    calls = [_qa_fail(), _output("good")]
    monkeypatch.setattr(runner, "run_task", lambda *a, **k: calls.pop(0))
    monkeypatch.setattr(runner, "diagnose_failure",
                        lambda *a, **k: DiagnosticResult(attribution="agent", consignes="x", reason="r"))
    ctx = RunContext(agents=[_StubAgentRoster()], client=SimpleNamespace(), divider=SimpleNamespace(),
                     aggregator=SimpleNamespace(), tagger=SimpleNamespace(), tracer=None, evaluator=None)
    out = runner.run_with_recovery(_task(), ctx)
    assert isinstance(out, Output)


def test_reeval_emits_second_qa_event_with_regenerated_spec(monkeypatch):
    # run_task est mocké → le SEUL QAEvaluatedEvent de la trace est celui de la ré-éval, émis par le runner
    monkeypatch.setattr(runner, "run_task", lambda *a, **k: _qa_fail())
    monkeypatch.setattr(runner, "diagnose_failure",
                        lambda *a, **k: DiagnosticResult(attribution="evaluator", consignes=None, reason="strict"))
    spec_v2 = EvaluatorSpec(criteria=[CriterionSpec(name="non_empty", gate=True)])
    good_qa = QAResult(task_id="t", agent_id="a", success=True, score=0.9, reason="ok",
                       criteria_results={"non_empty": True}, spec_used=spec_v2)
    monkeypatch.setattr(runner, "AdaptiveSpecEvaluator",
                        lambda client, failure_context=None: SimpleNamespace(evaluate=lambda task, output: good_qa))
    tracer = Tracer("s")
    out = runner.run_with_recovery(_task(), _ctx(tracer))
    assert isinstance(out, Output)
    qa_events = [e for e in tracer.events if isinstance(e, QAEvaluatedEvent)]
    assert len(qa_events) == 1
    assert qa_events[0].success is True
    assert qa_events[0].spec is not None and qa_events[0].spec.criteria[0].name == "non_empty"
    assert qa_events[0].agent_id == "a"
    # ordre : DiagnosedEvent AVANT le QAEvaluatedEvent de ré-éval
    types = [type(e).__name__ for e in tracer.events]
    assert types.index("DiagnosedEvent") < types.index("QAEvaluatedEvent")


def test_reeval_fail_still_emits_qa2_then_retries(monkeypatch):
    calls = [_qa_fail(), _output("recovered")]
    monkeypatch.setattr(runner, "run_task", lambda *a, **k: calls.pop(0))
    monkeypatch.setattr(runner, "diagnose_failure",
                        lambda *a, **k: DiagnosticResult(attribution="evaluator", consignes="clarify", reason="r"))
    bad_qa = QAResult(task_id="t", agent_id="a", success=False, score=0.1, reason="still bad", criteria_results={})
    monkeypatch.setattr(runner, "AdaptiveSpecEvaluator",
                        lambda client, failure_context=None: SimpleNamespace(evaluate=lambda task, output: bad_qa))
    tracer = Tracer("s")
    out = runner.run_with_recovery(_task(), _ctx(tracer))
    assert isinstance(out, Output) and out.content == "recovered"
    qa_events = [e for e in tracer.events if isinstance(e, QAEvaluatedEvent)]
    assert len(qa_events) == 1 and qa_events[0].success is False
```

- [ ] **Step 2: Lancer, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_d3_events.py -v`
Expected: FAIL (aucun `DiagnosedEvent`/`QAEvaluatedEvent` dans `tracer.events`).

- [ ] **Step 3: Implémenter les émissions dans `_route_diagnostic`**

Dans `src/aaosa/runtime/runner.py` :

1. Ajouter `DiagnosedEvent` à l'import `from aaosa.tracing.events import (...)`.
2. Remplacer le début de `_route_diagnostic` (lignes 343-345, de `diagnostic = diagnose_failure(...)`
   à `return _qa_failed(...)` sur `None`) par :

```python
    diagnostic = diagnose_failure(task, failure.output, failure.qa_result, ctx.client)

    # Pattern observer : le RUNNER émet (diagnostic.py reste pur). Émis y compris
    # sur échec LLM (diagnostic=None → unattributed, reason vide).
    if ctx.tracer is not None:
        ctx.tracer.emit(DiagnosedEvent(
            session_id=ctx.tracer.session_id,
            task_id=task.id,
            agent_id=failure.agent_id,
            attribution=diagnostic.attribution if diagnostic is not None else "unattributed",
            reason=diagnostic.reason if diagnostic is not None else "",
            consignes=diagnostic.consignes if diagnostic is not None else None,
        ))

    if diagnostic is None:
        return _qa_failed(task, attribution="unattributed", consignes_tried=False)
```

3. Dans la branche `evaluator`, après `qa2 = new_evaluator.evaluate(task, failure.output)` et
   avant `if qa2.success:`, insérer :

```python
        # Ré-évaluation VISIBLE : le runner trace la QA v2 (spec régénérée portée par spec_used).
        if ctx.tracer is not None:
            ctx.tracer.emit(QAEvaluatedEvent(
                session_id=ctx.tracer.session_id,
                task_id=task.id,
                agent_id=failure.agent_id,
                success=qa2.success,
                score=qa2.score,
                reason=qa2.reason,
                criteria_results=qa2.criteria_results,
                judge=qa2.judge,
                spec=qa2.spec_used,
            ))
```

- [ ] **Step 4: Lancer, vérifier le PASS (+ non-régression runtime)**

Run: `.venv\Scripts\python -m pytest tests/runtime/ -v`
Expected: PASS (6 nouveaux + tous les tests runner/d3_routes existants verts — ils passent `tracer=None`).

- [ ] **Step 5: Commit**

```bash
git add src/aaosa/runtime/runner.py tests/runtime/test_d3_events.py
git commit -m "feat(demo-p1): runner émet DiagnosedEvent + QA v2 visible (route evaluator)"
```

---

## PARTIE B — `build_graph` : reconstruction en arbre (TDD)

Réécriture en profondeur de `dashboard/graph_model.py`. L'ancien moteur (`_split_sub_runs`,
`_milestones_simple`, `_milestones_divided`, `_todo_simple`, `_todo_divided`, `_graph_sinks`,
`_build_nodes`, `_build_edges`, `_tool_node_id`) est remplacé. Sont CONSERVÉS tels quels :
les types de détail vague 2 (`DispatchDetail`, `AgentDetail`, `EvaluatorDetail`, `InputDetail`,
`OutputDetail`, `TestSetDetail`, `DividerDetail`+origin, `AggregatorDetail`, `ToolDetail`,
`ToolCallInfo`, `CandidateInfo`, `ClaimInfo`, `TagAcquiredInfo`), `_meta_record`,
`_make_input_detail`, `_agent_detail`, `_tool_groups`, `_EdgeAccumulator` (étendu flow),
`StepDetail` (étendu), `_evaluator_detail`/`_dispatch_detail`/`_scope_detail` (adaptés `_Pass`).

### Task 3: Modèle Pydantic étendu

**Files:**
- Modify: `dashboard/graph_model.py` (types uniquement)
- Test: `tests/dashboard/test_graph_model.py` (étendre)

- [ ] **Step 1: Écrire les tests des nouveaux champs**

Ajouter à `tests/dashboard/test_graph_model.py` (en conservant tout l'existant) :

```python
from dashboard.graph_model import (
    DiagnosticDetail,
    GraphEdge,
    GraphNode,
    GraphStep,
    RosterGapDetail,
    StepDetail,
    TaskBranch,
    TodoItem,
)


class TestSerieDModelExtensions:
    def test_edge_flow(self):
        e = GraphEdge(from_node="a", to="b", flow="descent")
        assert e.flow == "descent"
        assert GraphEdge(from_node="a", to="b").flow == "ascent"   # défaut documenté

    def test_edge_flow_serialized(self):
        e = GraphEdge(from_node="a", to="b", flow="transient")
        assert e.model_dump(by_alias=True) == {"from": "a", "to": "b", "flow": "transient"}

    def test_node_carries_task_and_agent(self):
        n = GraphNode(id="agent:t1:ag", layer="bottom", type="agent", label="ag",
                      task_id="t1", agent_id="ag")
        assert n.task_id == "t1" and n.agent_id == "ag"
        assert GraphNode(id="input", layer="top", type="input", label="Input").task_id is None

    def test_step_pass_index_default(self):
        step = GraphStep(milestone_type="dispatch", label="DISPATCH",
                         detail=StepDetail.empty(task_id="t", description="d"))
        assert step.pass_index == 0

    def test_diagnostic_detail(self):
        d = DiagnosticDetail(attribution="evaluator", reason="strict", consignes="relax",
                             route_taken="evaluator")
        assert d.route_taken == "evaluator"

    def test_roster_gap_detail(self):
        d = RosterGapDetail(missing_tags=["legal", "gdpr"])
        assert d.missing_tags == ["legal", "gdpr"]

    def test_step_detail_new_fields_default_none(self):
        d = StepDetail.empty(task_id="t", description="x")
        assert d.diagnostic is None and d.roster_gap is None

    def test_todo_item_hierarchy(self):
        t = TodoItem(id="s1", description="x", state="current", is_root=False,
                     parent_id="root", depth=1, first_step_index=4, note="pass 2")
        assert t.parent_id == "root" and t.depth == 1 and t.first_step_index == 4
        bare = TodoItem(id="r", description="x", state="done", is_root=True)
        assert bare.parent_id is None and bare.depth == 0 and bare.first_step_index is None

    def test_task_branch(self):
        b = TaskBranch(id="s1", parent_id="root", depth=1, order_index=0, description="sub")
        assert b.depth == 1

    def test_new_outcomes_and_types_accepted(self):
        step = GraphStep(milestone_type="diagnostic", label="DIAGNOSTIC", outcome="diagnosed",
                         detail=StepDetail.empty(task_id="t", description="d"))
        assert step.outcome == "diagnosed"
        n = GraphNode(id="roster_gap:t1", layer="center", type="roster_gap", label="GAP", task_id="t1")
        assert n.type == "roster_gap"
```

- [ ] **Step 2: Lancer, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_graph_model.py -v`
Expected: FAIL (ImportError `DiagnosticDetail`/`RosterGapDetail`/`TaskBranch` ; `flow`/`pass_index` inconnus).

- [ ] **Step 3: Étendre les types dans `dashboard/graph_model.py`**

Remplacer les lignes de types (24-27) par le bloc « Contrat cible » ci-dessus (avec `EdgeFlow`), puis :

1. `GraphNode` — ajouter :

```python
    task_id: str | None = None   # appartenance de branche (None pour input/tagger/output)
    agent_id: str | None = None  # nœud agent : agent_id réel (badge ×N côté frontend)
```

2. `GraphEdge` — ajouter :

```python
    flow: EdgeFlow = "ascent"
```

3. Ajouter après `DividerSubTaskInfo` :

```python
class DiagnosticDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attribution: Literal["agent", "evaluator", "task_spec", "unattributed"]
    reason: str
    consignes: str | None = None
    route_taken: Literal["agent", "evaluator", "task_spec", "stop"]   # stop = unattributed


class RosterGapDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    missing_tags: list[str] = Field(default_factory=list)
```

4. `DividerDetail` — ajouter :

```python
    origin: Literal["recovery", "diagnostic"] = "recovery"   # D1 (unassigned) vs D3 (task_spec)
```

5. `StepDetail` — ajouter :

```python
    diagnostic: DiagnosticDetail | None = None
    roster_gap: RosterGapDetail | None = None
```

6. `TodoItem` — ajouter :

```python
    parent_id: str | None = None
    depth: int = 0
    first_step_index: int | None = None   # point de navigation timeline (calcul backend)
    note: str | None = None               # annotation de marge : "pass 2", "roster gap", "route X"
```

7. `GraphStep` — ajouter :

```python
    pass_index: int = 0   # 0 = première tentative, 1 = passe retry (D3)
```

8. Ajouter avant `GraphModel`, puis le champ dans `GraphModel` :

```python
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
```

Importer `DiagnosedEvent` dans le bloc d'imports `aaosa.tracing.events` (utilisé dès Task 4).

- [ ] **Step 4: Lancer, vérifier le PASS**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_graph_model.py::TestSerieDModelExtensions -v`
Expected: PASS (11 tests). Le reste de la suite dashboard reste vert (champs additifs avec défauts).

- [ ] **Step 5: Lancer toute la suite dashboard (non-régression additive)**

Run: `.venv\Scripts\python -m pytest tests/dashboard/ -q`
Expected: PASS — aucune réécriture du builder encore.

- [ ] **Step 6: Commit**

```bash
git add dashboard/graph_model.py tests/dashboard/test_graph_model.py
git commit -m "feat(demo-p1): modèle graphe étendu — flow, pass_index, diagnostic/roster_gap, TODO hiérarchique, TaskBranch"
```

---

### Task 4: Parsing — partition `task_id`, passes, `_TaskRun`, arbre de tâches

Remplace l'heuristique `_split_sub_runs` (frontière Phase1) par une partition fiable par
`_BaseEvent.task_id`, avec découpage en **passes** (nouvelle séquence Phase1 après un
`DiagnosedEvent` = passe retry) et capture de `diagnosed`/`reeval`/`divided`/`aggregated`/`roster_gap`.

**Files:**
- Modify: `dashboard/graph_model.py`
- Test: `tests/dashboard/test_build_graph_tree.py` (créer)

- [ ] **Step 1: Écrire les tests de parsing**

Créer `tests/dashboard/test_build_graph_tree.py` :

```python
from aaosa.qa.spec import CriterionSpec, EvaluatorSpec
from aaosa.tracing.events import (
    DiagnosedEvent,
    DispatchedEvent,
    DividedSubTask,
    ExecutedEvent,
    Phase1FilteredEvent,
    Phase2ClaimedEvent,
    QAEvaluatedEvent,
    RosterGapEvent,
    TaskAggregatedEvent,
    TaskDividedEvent,
    ToolCalledEvent,
    UnassignedEvent,
)
from aaosa.tracing.store import SessionMeta, SessionTaskRecord
from dashboard.graph_model import _build_tree, _parse_runs, build_graph

SID = "s"


def p1(tid, aid, passed=True, fit=0.9):
    return Phase1FilteredEvent(session_id=SID, task_id=tid, agent_id=aid, passed=passed, fit_score=fit)


def p2(tid, aid, decision="claim"):
    return Phase2ClaimedEvent(session_id=SID, task_id=tid, agent_id=aid, decision=decision, justification="mine")


def disp(tid, aid):
    return DispatchedEvent(session_id=SID, task_id=tid, agent_id=aid, reason="sole claimer")


def ex(tid, aid, content="content"):
    return ExecutedEvent(session_id=SID, task_id=tid, agent_id=aid, output_summary=content[:20], output_content=content)


def qa(tid, aid, success=True, score=None, spec=None):
    return QAEvaluatedEvent(session_id=SID, task_id=tid, agent_id=aid, success=success,
                            score=score if score is not None else (1.0 if success else 0.2),
                            reason="ok" if success else "bad", spec=spec)


def diag(tid, aid, attribution, reason="r", consignes=None):
    return DiagnosedEvent(session_id=SID, task_id=tid, agent_id=aid,
                          attribution=attribution, reason=reason, consignes=consignes)


def tool(tid, aid, name):
    return ToolCalledEvent(session_id=SID, task_id=tid, agent_id=aid, tool_name=name,
                           arguments={}, result="r", latency_ms=0.1)


def divided(parent, subs):
    """subs = [(id, description, depends_on, required_tags)]"""
    return TaskDividedEvent(session_id=SID, task_id=parent, sub_tasks=[
        DividedSubTask(id=i, description=d, depends_on=deps, required_tags=tags)
        for (i, d, deps, tags) in subs
    ])


def aggregated(parent, sub_ids, content="final"):
    return TaskAggregatedEvent(session_id=SID, task_id=parent, sub_task_ids=sub_ids,
                               output_summary=content, output_content=content)


def meta(task_id, desc, tags=None):
    return SessionMeta(
        session_id=SID, started_at="2026-01-01T00:00:00Z", ended_at="2026-01-01T00:01:00Z",
        tasks=[SessionTaskRecord(id=task_id, description=desc, winner_agent_id=None,
                                 outcome="qa_pass",
                                 required_tags={"python": 50} if tags is None else tags)],
        agent_ids=["ag"],
    )


def simple_pass(tid, aid="ag", success=True, with_tool=None, content="content"):
    evs = [p1(tid, aid), p2(tid, aid), disp(tid, aid)]
    if with_tool:
        evs.append(tool(tid, aid, with_tool))
    evs += [ex(tid, aid, content), qa(tid, aid, success=success)]
    return evs


class TestParseRuns:
    def test_partition_by_task_id(self):
        events = simple_pass("t1") + simple_pass("t2", content="other")
        runs = _parse_runs(events)
        assert set(runs) == {"t1", "t2"}
        assert runs["t1"].passes[0].executed.output_content == "content"
        assert runs["t2"].passes[0].executed.output_content == "other"

    def test_single_pass_no_diag(self):
        runs = _parse_runs(simple_pass("t1"))
        r = runs["t1"]
        assert len(r.passes) == 1
        assert r.diagnosed is None and r.reeval is None
        assert r.passes[0].winner_id == "ag"
        assert r.succeeded is True

    def test_retry_pass_after_diagnosed(self):
        # pass 0 (fail) → diagnosed agent → pass 1 (success)
        events = (simple_pass("t1", success=False)
                  + [diag("t1", "ag", "agent", consignes="be precise")]
                  + simple_pass("t1", success=True, content="fixed"))
        r = _parse_runs(events)["t1"]
        assert len(r.passes) == 2
        assert r.passes[0].outcome == "qa_fail"
        assert r.passes[1].outcome == "qa_pass"
        assert r.diagnosed.attribution == "agent"
        assert r.reeval is None
        assert r.succeeded is True

    def test_reeval_captured_separately(self):
        # route evaluator : QA post-diag SANS nouveau Phase1 = ré-éval v2
        spec_v2 = EvaluatorSpec(criteria=[CriterionSpec(name="non_empty", gate=True)])
        events = (simple_pass("t1", success=False)
                  + [diag("t1", "ag", "evaluator"), qa("t1", "ag", success=True, spec=spec_v2)])
        r = _parse_runs(events)["t1"]
        assert len(r.passes) == 1
        assert r.reeval is not None and r.reeval.success is True
        assert r.reeval.spec.criteria[0].name == "non_empty"
        assert r.succeeded is True       # la ré-éval valide l'output original

    def test_reeval_fail_then_retry(self):
        events = (simple_pass("t1", success=False)
                  + [diag("t1", "ag", "evaluator", consignes="clarify"), qa("t1", "ag", success=False)]
                  + simple_pass("t1", success=True))
        r = _parse_runs(events)["t1"]
        assert r.reeval is not None and r.reeval.success is False
        assert len(r.passes) == 2
        assert r.succeeded is True

    def test_roster_gap_task(self):
        events = [RosterGapEvent(session_id=SID, task_id="t1", missing_tags=["legal"])]
        r = _parse_runs(events)["t1"]
        assert r.roster_gap is not None
        assert r.passes == []
        assert r.succeeded is False

    def test_unassigned_then_divided(self):
        events = ([p1("t1", "ag", passed=False),
                   UnassignedEvent(session_id=SID, task_id="t1", reason="no claim"),
                   divided("t1", [("s1", "part A", [], {"python": 50})])]
                  + simple_pass("s1"))
        runs = _parse_runs(events)
        assert runs["t1"].divided is not None
        assert runs["t1"].passes[0].outcome == "unassigned"
        assert runs["s1"].succeeded is True


class TestBuildTree:
    def test_root_from_meta(self):
        events = simple_pass("t1")
        tree = _build_tree(events, meta("t1", "do it"))
        assert tree.root_id == "t1"
        assert tree.children("t1") == []

    def test_recursive_tree_from_all_divided_events(self):
        events = (
            [p1("root", "ag", passed=False), UnassignedEvent(session_id=SID, task_id="root", reason="r"),
             divided("root", [("c1", "part 1", [], {"python": 50}), ("c2", "part 2", [], {"python": 50})])]
            + [p1("c1", "ag", passed=False), UnassignedEvent(session_id=SID, task_id="c1", reason="r"),
               divided("c1", [("g1", "deep 1", [], {"python": 50})])]
            + simple_pass("g1") + simple_pass("c2")
            + [aggregated("root", ["c1", "c2"])]
        )
        tree = _build_tree(events, meta("root", "big"))
        assert tree.root_id == "root"
        assert tree.children("root") == ["c1", "c2"]
        assert tree.children("c1") == ["g1"]
        assert tree.depth("g1") == 2
        assert tree.parent("g1") == "c1"
        assert tree.description("c1") == "part 1"

    def test_tasks_exported_on_graph_model(self):
        events = ([p1("root", "ag", passed=False), UnassignedEvent(session_id=SID, task_id="root", reason="r"),
                   divided("root", [("c1", "part 1", [], {"python": 50})])] + simple_pass("c1"))
        graph = build_graph(events, meta("root", "big"))
        by_id = {t.id: t for t in graph.tasks}
        assert by_id["root"].parent_id is None and by_id["root"].depth == 0
        assert by_id["c1"].parent_id == "root" and by_id["c1"].depth == 1
        assert by_id["c1"].description == "part 1"
        assert by_id["root"].description == "big"
```

- [ ] **Step 2: Lancer, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_build_graph_tree.py -v`
Expected: FAIL (ImportError `_build_tree`, `_parse_runs`).

- [ ] **Step 3: Implémenter le parsing**

Dans `dashboard/graph_model.py`, SUPPRIMER `_split_sub_runs` et renommer/adapter `_SubTaskRun` en
`_Pass` (corps identique, plus de paramètre task_id — il vit sur `_TaskRun`). Ajouter :

```python
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
                        self.passes.append(_Pass(current))
                    current = [e]
                    continue
                if isinstance(e, QAEvaluatedEvent):
                    self.reeval = e   # ré-éval v2 (route evaluator) : QA post-diag sans nouveau Phase1
                    continue
            current.append(e)
        if current:
            self.passes.append(_Pass(current))

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
                 first_idx: dict[str, int]):
        self.root_id = root_id
        self._children = children
        self._parents = parents
        self._descriptions = descriptions
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
    first_idx: dict[str, int] = {}
    for i, e in enumerate(events):
        first_idx.setdefault(e.task_id, i)
        if isinstance(e, TaskDividedEvent):
            children[e.task_id] = [st.id for st in e.sub_tasks]
            for st in e.sub_tasks:
                parents[st.id] = e.task_id
                descriptions[st.id] = st.description

    if session_meta is not None and session_meta.tasks:
        root_id = session_meta.tasks[0].id
        descriptions[root_id] = session_meta.tasks[0].description
    else:
        root_id = next((tid for tid in first_idx if tid not in parents), "task")
    return _Tree(root_id, children, parents, descriptions, first_idx)


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
```

`build_graph` n'est branché sur ces helpers qu'en Task 6 ; pour faire passer
`test_tasks_exported_on_graph_model` dès maintenant, modifier `build_graph` pour calculer
`tree = _build_tree(events, session_meta)` et passer `tasks=_task_branches(tree)` au `GraphModel`
retourné (le reste de `build_graph` vague 2 reste en l'état provisoirement — il sera remplacé en Task 6).

- [ ] **Step 4: Lancer, vérifier le PASS**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_build_graph_tree.py -v`
Expected: PASS. ATTENTION : `_split_sub_runs` supprimé → le `build_graph` vague 2 doit provisoirement
utiliser `_parse_runs` à la place pour ne pas casser l'import (remplacer son appel par
`sub_runs = [r.passes[0] for r in _parse_runs(events).values() if r.passes]` et adapter
`_milestones_*` qui lisaient `.task_id` sur le run : passer le `task_id` séparément OU laisser
temporairement les anciens tests rouges — choix assumé : **les suites
`test_build_graph_milestones/a4/d2` peuvent être rouges entre Task 4 et Task 11**, la suite
`test_build_graph_tree.py` fait foi pendant la réécriture).

- [ ] **Step 5: Commit**

```bash
git add dashboard/graph_model.py tests/dashboard/test_build_graph_tree.py
git commit -m "feat(demo-p1): partition task_id + passes retry + arbre de tâches (_parse_runs/_build_tree)"
```

---

### Task 5: Structure statique — nœuds + arêtes namespacés, sinks, exits

**Files:**
- Modify: `dashboard/graph_model.py`
- Test: `tests/dashboard/test_build_graph_tree.py`

- [ ] **Step 1: Écrire les tests de structure**

Ajouter à `tests/dashboard/test_build_graph_tree.py` :

```python
def divided_fixture():
    """root unassigned → divisé en s1 (tool) et s2 (dépend de s1), agrégation réelle absente
    (s2 consomme s1, sink unique = s2 → court-circuit)."""
    return ([p1("root", "ag", passed=False),
             UnassignedEvent(session_id=SID, task_id="root", reason="no claim"),
             divided("root", [("s1", "investigate", [], {"python": 50}),
                              ("s2", "fix", ["s1"], {"python": 50})])]
            + simple_pass("s1", with_tool="grep", content="c1")
            + simple_pass("s2", content="c2"))


def divided_agg_fixture():
    """root → 2 sous-tâches indépendantes → 2 sinks → agrégation réelle."""
    return ([p1("root", "ag", passed=False),
             UnassignedEvent(session_id=SID, task_id="root", reason="no claim"),
             divided("root", [("s1", "part A", [], {"python": 50}),
                              ("s2", "part B", [], {"python": 50})])]
            + simple_pass("s1", content="c1") + simple_pass("s2", content="c2")
            + [aggregated("root", ["s1", "s2"])])


class TestStructure:
    def test_namespaced_nodes_simple_run(self):
        graph = build_graph(simple_pass("t1"), meta("t1", "do it"))
        ids = {n.id for n in graph.nodes}
        assert {"input", "tagger", "output", "dispatch:t1", "agent:t1:ag", "evaluator:t1"} <= ids
        assert "testset" not in ids                       # retiré du graphe série D
        agent = next(n for n in graph.nodes if n.type == "agent")
        assert agent.task_id == "t1" and agent.agent_id == "ag"

    def test_simple_run_edges_and_flows(self):
        graph = build_graph(simple_pass("t1"), meta("t1", "do it"))
        flows = {(e.from_node, e.to): e.flow for e in graph.edges}
        assert flows[("input", "tagger")] == "ascent"
        assert flows[("tagger", "dispatch:t1")] == "ascent"
        assert flows[("dispatch:t1", "agent:t1:ag")] == "ascent"
        assert flows[("agent:t1:ag", "evaluator:t1")] == "descent"
        assert flows[("evaluator:t1", "output")] == "descent"

    def test_tool_nodes_per_branch(self):
        graph = build_graph(simple_pass("t1", with_tool="grep"), meta("t1", "do it"))
        ids = {n.id for n in graph.nodes}
        assert "tool:t1:grep" in ids
        flows = {(e.from_node, e.to): e.flow for e in graph.edges}
        assert flows[("agent:t1:ag", "tool:t1:grep")] == "transient"

    def test_divided_short_circuit_no_aggregator(self):
        graph = build_graph(divided_fixture(), meta("root", "big"))
        ids = {n.id for n in graph.nodes}
        assert "divider:root" in ids and "aggregator:root" not in ids
        flows = {(e.from_node, e.to): e.flow for e in graph.edges}
        # division D1 : le dispatch raté monte vers le divider
        assert flows[("dispatch:root", "divider:root")] == "ascent"
        # bus d'émission : risers vers chaque branche
        assert flows[("divider:root", "dispatch:s1")] == "ascent"
        assert flows[("divider:root", "dispatch:s2")] == "ascent"
        # dep consommée : s1 → s2 en transient
        assert flows[("evaluator:s1", "dispatch:s2")] == "transient"
        # court-circuit : la descente du sink s2 file à OUTPUT
        assert flows[("evaluator:s2", "output")] == "descent"

    def test_divided_aggregated_structure(self):
        graph = build_graph(divided_agg_fixture(), meta("root", "big"))
        ids = {n.id for n in graph.nodes}
        assert "aggregator:root" in ids
        flows = {(e.from_node, e.to): e.flow for e in graph.edges}
        assert flows[("evaluator:s1", "aggregator:root")] == "descent"
        assert flows[("evaluator:s2", "aggregator:root")] == "descent"
        assert flows[("aggregator:root", "output")] == "descent"
        assert ("evaluator:s1", "output") not in flows

    def test_recursive_division_nested_pair(self):
        events = (
            [p1("root", "ag", passed=False), UnassignedEvent(session_id=SID, task_id="root", reason="r"),
             divided("root", [("c1", "part 1", [], {"python": 50}), ("c2", "part 2", [], {"python": 50})])]
            + [p1("c1", "ag", passed=False), UnassignedEvent(session_id=SID, task_id="c1", reason="r"),
               divided("c1", [("g1", "deep A", [], {"python": 50}), ("g2", "deep B", [], {"python": 50})])]
            + simple_pass("g1") + simple_pass("g2")
            + [aggregated("c1", ["g1", "g2"], content="c1 synth")]
            + simple_pass("c2")
            + [aggregated("root", ["c1", "c2"])]
        )
        graph = build_graph(events, meta("root", "big"))
        ids = {n.id for n in graph.nodes}
        assert {"divider:root", "aggregator:root", "divider:c1", "aggregator:c1"} <= ids
        flows = {(e.from_node, e.to): e.flow for e in graph.edges}
        # paire par niveau : l'aggregator enfant descend vers l'aggregator parent
        assert flows[("aggregator:c1", "aggregator:root")] == "descent"
        assert flows[("evaluator:g1", "aggregator:c1")] == "descent"
```

- [ ] **Step 2: Lancer, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_build_graph_tree.py::TestStructure -v`
Expected: FAIL (nœuds non namespacés, pas de `tagger`, `testset` présent).

- [ ] **Step 3: Implémenter la structure statique**

Dans `dashboard/graph_model.py`, SUPPRIMER `_build_nodes`, `_build_edges`, `_tool_node_id`,
`_distinct_tools`, `_has_qa_fail`, `_graph_sinks`. Ajouter :

```python
def _nid(kind: str, tid: str, extra: str | None = None) -> str:
    return f"{kind}:{tid}" + (f":{extra}" if extra else "")


def _has_result(tid: str, runs: dict[str, _TaskRun]) -> bool:
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


def _sink_ids(divided_ev: TaskDividedEvent, runs: dict[str, _TaskRun]) -> list[str]:
    """Même règle que le runtime `_sinks` : un réussi non consommé par un réussi.
    Réussi = _has_result (couvre les sous-tâches elles-mêmes divisées)."""
    ok = {st.id for st in divided_ev.sub_tasks if _has_result(st.id, runs)}
    consumed = {dep for st in divided_ev.sub_tasks if st.id in ok
                for dep in st.depends_on if dep in ok}
    return [st.id for st in divided_ev.sub_tasks if st.id in ok and st.id not in consumed]


def _exit_node(tid: str, runs: dict[str, _TaskRun]) -> str | None:
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


def _division_origin(run: _TaskRun) -> Literal["recovery", "diagnostic"]:
    if run.diagnosed is not None and run.diagnosed.attribution == "task_spec":
        return "diagnostic"
    return "recovery"


def _divider_anchor(run: _TaskRun, tid: str) -> str | None:
    """D'où monte l'arête vers divider:<tid> : DIAG (D3) ou le dispatch raté (D1)."""
    if _division_origin(run) == "diagnostic":
        return _nid("diagnostic", tid)
    if run.passes:
        return _nid("dispatch", tid)
    return None


def _winners(run: _TaskRun) -> list[str]:
    """Winners distincts à travers les passes (ordre d'apparition)."""
    seen: list[str] = []
    for p in run.passes:
        w = p.winner_id
        if w and w not in seen:
            seen.append(w)
    return seen


def _branch_tools(run: _TaskRun) -> list[tuple[str, str]]:
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
    tree: _Tree, runs: dict[str, _TaskRun], root_tags: dict[str, int],
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
        if run.diagnosed is not None:
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
```

Brancher dans `build_graph` (toujours provisoire pour les steps — Task 6 les remplace) :

```python
def build_graph(events: list[ClaimEvent], session_meta: SessionMeta | None = None) -> GraphModel:
    tree = _build_tree(events, session_meta)
    runs = _parse_runs(events)
    root_record = _meta_record(session_meta, tree.root_id)
    root_tags = dict(root_record.required_tags) if root_record is not None else {}
    nodes, edges = _build_structure(tree, runs, root_tags)
    steps = []   # Task 6+ : walk récursif
    return GraphModel(nodes=nodes, edges=edges, steps=steps, tasks=_task_branches(tree))
```

- [ ] **Step 4: Lancer, vérifier le PASS**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_build_graph_tree.py -v`
Expected: PASS (TestParseRuns + TestBuildTree + TestStructure). `test_tasks_exported_on_graph_model`
reste vert.

- [ ] **Step 5: Commit**

```bash
git add dashboard/graph_model.py tests/dashboard/test_build_graph_tree.py
git commit -m "feat(demo-p1): structure statique arbre — nœuds namespacés, flows, sinks/exits, paire par niveau"
```

---

### Task 6: Walk récursif unique — `_build_steps` (run simple = arbre dégénéré)

Implémente le walk COMPLET (simple + divisé + D3 + roster_gap) en une fois — les Tasks 7-9 le
verrouillent par tests sur les chemins divisé/D3/gap. Cette task ne teste que le run simple.

**Files:**
- Modify: `dashboard/graph_model.py`
- Test: `tests/dashboard/test_build_graph_tree.py`

- [ ] **Step 1: Écrire les tests du run simple (arbre dégénéré)**

Ajouter à `tests/dashboard/test_build_graph_tree.py` :

```python
class TestSimpleRunWalk:
    def test_milestone_sequence_with_tagger(self):
        graph = build_graph(simple_pass("t1"), meta("t1", "do it"))
        assert [s.milestone_type for s in graph.steps] == [
            "input", "tagger", "dispatch", "agent", "evaluator", "output"]

    def test_no_tagger_without_required_tags(self):
        graph = build_graph(simple_pass("t1"), meta("t1", "do it", tags={}))
        types = [s.milestone_type for s in graph.steps]
        assert "tagger" not in types
        assert "tagger" not in {n.id for n in graph.nodes}

    def test_dispatch_milestone_namespaced(self):
        graph = build_graph(simple_pass("t1"), meta("t1", "do it"))
        d = next(s for s in graph.steps if s.milestone_type == "dispatch")
        assert "dispatch:t1" in d.active_nodes and "agent:t1:ag" in d.active_nodes
        pairs = {(e.from_node, e.to) for e in d.active_edges}
        assert ("tagger", "dispatch:t1") in pairs
        assert ("dispatch:t1", "agent:t1:ag") in pairs
        assert d.winner_agent_id == "ag" and d.pass_index == 0

    def test_evaluator_and_output(self):
        graph = build_graph(simple_pass("t1"), meta("t1", "do it"))
        ev = next(s for s in graph.steps if s.milestone_type == "evaluator")
        assert ev.outcome == "qa_pass" and ev.active_nodes == ["evaluator:t1"]
        out = graph.steps[-1]
        assert out.milestone_type == "output"
        pairs = {(e.from_node, e.to) for e in out.active_edges}
        assert ("evaluator:t1", "output") in pairs       # backbone cumulatif
        assert out.detail.output.output_content == "content"

    def test_tool_milestones_rle(self):
        evs = [p1("t1", "ag"), p2("t1", "ag"), disp("t1", "ag"),
               tool("t1", "ag", "grep"), tool("t1", "ag", "grep"), tool("t1", "ag", "read"),
               ex("t1", "ag"), qa("t1", "ag")]
        graph = build_graph(evs, meta("t1", "do it"))
        tool_steps = [s for s in graph.steps if s.milestone_type == "tool"]
        assert [s.detail.tool.tool_name for s in tool_steps] == ["grep", "read"]
        assert len(tool_steps[0].detail.tool.calls) == 2
        assert "tool:t1:grep" in tool_steps[0].active_nodes

    def test_qa_fail_no_output_milestone(self):
        # qa_fail SANS DiagnosedEvent (mode health check) : la branche s'arrête à l'evaluator
        graph = build_graph(simple_pass("t1", success=False), meta("t1", "do it"))
        assert graph.steps[-1].milestone_type == "evaluator"
        assert graph.steps[-1].outcome == "qa_fail"

    def test_unassigned_stops_at_dispatch(self):
        evs = [p1("t1", "ag", passed=False),
               UnassignedEvent(session_id=SID, task_id="t1", reason="no claim")]
        graph = build_graph(evs, meta("t1", "do it"))
        assert graph.steps[-1].milestone_type == "dispatch"
        assert graph.steps[-1].winner_agent_id is None
        assert graph.steps[-1].detail.dispatch.unassigned_reason == "no claim"
```

- [ ] **Step 2: Lancer, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_build_graph_tree.py::TestSimpleRunWalk -v`
Expected: FAIL (`steps == []`).

- [ ] **Step 3: Amender `_Tree` (tags) + `_EdgeAccumulator` (flow)**

1. `_Tree` : ajouter un paramètre/attribut `tags` (dict `tid -> required_tags`) au constructeur
(`self._tags = tags`) et la méthode :

```python
    def tags(self, tid: str) -> dict[str, int]:
        return dict(self._tags.get(tid, {}))
```

Remplacer `_build_tree` par la version complète :

```python
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
        descriptions[root_id] = session_meta.tasks[0].description
        tags[root_id] = dict(session_meta.tasks[0].required_tags)
    else:
        root_id = next((tid for tid in first_idx if tid not in parents), "task")
    return _Tree(root_id, children, parents, descriptions, tags, first_idx)
```

(Adapter la signature de `_Tree.__init__` : `tags` s'insère avant `first_idx`.)

2. `_EdgeAccumulator` : porter le flow.

```python
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
```

- [ ] **Step 4: Implémenter le walk complet**

SUPPRIMER `_milestones_simple`, `_milestones_divided`, `_todo_simple`, `_todo_divided`,
`_root_state`, `_sub_desc`, `_sub_tags`, l'ancien `_tool_milestones`. Adapter `_scope_detail` en
`_pass_detail` et ajouter le walk :

```python
def _pass_detail(input_detail: InputDetail, p: _Pass, tid: str) -> StepDetail:
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
```

(`_dispatch_detail` et `_evaluator_detail` : remplacer leur paramètre `run` par `p` — corps inchangé.)

```python
def _tool_milestones(tid: str, p: _Pass, owner_detail: StepDetail, acc: _EdgeAccumulator) -> list[GraphStep]:
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


def _walk(tid: str, entry_anchor: str, tree: _Tree, runs: dict[str, _TaskRun],
          acc: _EdgeAccumulator) -> list[GraphStep]:
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


def _output_detail(exit_id: str, runs: dict[str, _TaskRun]) -> OutputDetail:
    owner = runs[_exit_owner(exit_id)]
    if exit_id.startswith("aggregator:"):
        ev = owner.aggregated
        return OutputDetail(produced=True, output_summary=ev.output_summary,
                            output_content=ev.output_content, llm_metadata=ev.llm_metadata)
    executed = owner.passes[-1].executed
    return OutputDetail(produced=True, output_summary=executed.output_summary,
                        output_content=executed.output_content, llm_metadata=executed.llm_metadata)


def _build_steps(tree: _Tree, runs: dict[str, _TaskRun],
                 session_meta: SessionMeta | None) -> list[GraphStep]:
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
    return steps
```

Brancher dans `build_graph` :

```python
def build_graph(events: list[ClaimEvent], session_meta: SessionMeta | None = None) -> GraphModel:
    tree = _build_tree(events, session_meta)
    runs = _parse_runs(events)
    nodes, edges = _build_structure(tree, runs, tree.tags(tree.root_id))
    steps = _build_steps(tree, runs, session_meta)
    return GraphModel(nodes=nodes, edges=edges, steps=steps, tasks=_task_branches(tree))
```

NOTE : `_build_structure` prend désormais `tree.tags(root)` (et plus le meta-record) — la condition
tagger est identique des deux côtés. Le `root_tags` calculé en Task 5 dans `build_graph` disparaît.
Cas « zéro event » (session vide) : `_build_tree` renvoie la racine du meta → INPUT seul, pas de crash.

- [ ] **Step 5: Lancer, vérifier le PASS**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_build_graph_tree.py -v`
Expected: PASS (toute la suite tree, walk simple inclus).

- [ ] **Step 6: Commit**

```bash
git add dashboard/graph_model.py tests/dashboard/test_build_graph_tree.py
git commit -m "feat(demo-p1): walk récursif unique — run simple = arbre dégénéré (jalons namespacés)"
```

---

### Task 7: Walk — récursion D1 (paire par niveau, court-circuit, collecte)

Le walk est déjà implémenté (Task 6) ; cette task le VERROUILLE sur les chemins divisés et corrige
les écarts éventuels.

**Files:**
- Test: `tests/dashboard/test_build_graph_tree.py`
- Modify (si écart): `dashboard/graph_model.py`

- [ ] **Step 1: Écrire les tests du run divisé + récursion**

Ajouter à `tests/dashboard/test_build_graph_tree.py` :

```python
class TestDividedWalk:
    def test_sequence_short_circuit(self):
        # divided_fixture : s2 consomme s1 → sink unique s2 → PAS d'aggregator, OUTPUT depuis s2
        graph = build_graph(divided_fixture(), meta("root", "big"))
        types = [s.milestone_type for s in graph.steps]
        assert types == ["input", "tagger", "dispatch",                  # racine (unassigned)
                         "divider",
                         "dispatch", "tool", "agent", "evaluator",       # s1
                         "dispatch", "agent", "evaluator",               # s2
                         "output"]
        assert "aggregator" not in types
        out = graph.steps[-1]
        assert out.detail.output.output_content == "c2"                  # l'output du sink, pas une synthèse

    def test_sequence_aggregated(self):
        graph = build_graph(divided_agg_fixture(), meta("root", "big"))
        types = [s.milestone_type for s in graph.steps]
        assert types[-2:] == ["aggregator", "output"]
        agg = next(s for s in graph.steps if s.milestone_type == "aggregator")
        assert agg.detail.aggregator.aggregated is True
        assert agg.detail.aggregator.collected == 2 and agg.detail.aggregator.total == 2
        out = graph.steps[-1]
        assert out.detail.output.output_content == "final"

    def test_collect_story_on_sink_evaluator(self):
        graph = build_graph(divided_agg_fixture(), meta("root", "big"))
        ev1 = next(s for s in graph.steps if s.milestone_type == "evaluator" and s.sub_task_id == "s1")
        assert "aggregator:root" in ev1.active_nodes
        pairs = {(e.from_node, e.to) for e in ev1.active_edges}
        assert ("evaluator:s1", "aggregator:root") in pairs
        assert ev1.detail.aggregator.collected == 1 and ev1.detail.aggregator.total == 2

    def test_divider_milestone_carries_subtasks_and_origin(self):
        graph = build_graph(divided_agg_fixture(), meta("root", "big"))
        div = next(s for s in graph.steps if s.milestone_type == "divider")
        assert div.detail.divider.origin == "recovery"            # division D1 (unassigned)
        assert [st.id for st in div.detail.divider.sub_tasks] == ["s1", "s2"]
        assert div.detail.divider.sub_tasks[0].required_tags == {"python": 50}

    def test_recursive_walk_nested(self):
        # même fixture que test_recursive_division_nested_pair (Task 5)
        events = (
            [p1("root", "ag", passed=False), UnassignedEvent(session_id=SID, task_id="root", reason="r"),
             divided("root", [("c1", "part 1", [], {"python": 50}), ("c2", "part 2", [], {"python": 50})])]
            + [p1("c1", "ag", passed=False), UnassignedEvent(session_id=SID, task_id="c1", reason="r"),
               divided("c1", [("g1", "deep A", [], {"python": 50}), ("g2", "deep B", [], {"python": 50})])]
            + simple_pass("g1") + simple_pass("g2")
            + [aggregated("c1", ["g1", "g2"], content="c1 synth")]
            + simple_pass("c2")
            + [aggregated("root", ["c1", "c2"])]
        )
        graph = build_graph(events, meta("root", "big"))
        seq = [(s.milestone_type, s.sub_task_id) for s in graph.steps]
        # l'arbre se déroule en profondeur : c1 se divise AVANT que c2 ne tourne
        assert seq.index(("divider", "c1")) < seq.index(("dispatch", "c2"))
        assert seq.index(("aggregator", "c1")) < seq.index(("dispatch", "c2"))
        # deux aggregators, niveau enfant puis racine
        aggs = [s.sub_task_id for s in graph.steps if s.milestone_type == "aggregator"]
        assert aggs == ["c1", "root"]
        # le step detail de chaque sous-branche est scopé
        a_g1 = next(s for s in graph.steps if s.milestone_type == "agent" and s.sub_task_id == "g1")
        assert a_g1.detail.input.description == "deep A"

    def test_subtask_unassigned_no_recovery(self):
        # une sous-tâche unassigned NON divisée (gap de claim) : sa branche s'arrête au dispatch
        events = ([p1("root", "ag", passed=False),
                   UnassignedEvent(session_id=SID, task_id="root", reason="r"),
                   divided("root", [("s1", "ok", [], {"python": 50}),
                                    ("s2", "nobody", [], {"python": 50})])]
                  + simple_pass("s1")
                  + [p1("s2", "ag", passed=False),
                     UnassignedEvent(session_id=SID, task_id="s2", reason="no claim")])
        graph = build_graph(events, meta("root", "big"))
        s2_types = [s.milestone_type for s in graph.steps if s.sub_task_id == "s2"]
        assert s2_types == ["dispatch"]
        # s1 est l'unique sink → court-circuit → OUTPUT depuis s1
        assert graph.steps[-1].milestone_type == "output"
        assert graph.steps[-1].detail.output.output_content == "content"
```

- [ ] **Step 2: Lancer, corriger les écarts jusqu'au PASS**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_build_graph_tree.py::TestDividedWalk -v`
Expected: PASS direct si Task 6 est correcte. Si un test échoue, corriger `_walk` (points sensibles :
ordre des enfants = `tree.children` trié par premier event ; le `continue` sur `winner is None`
ne doit PAS sauter le bloc division qui est hors de la boucle des passes).

- [ ] **Step 3: Commit**

```bash
git add dashboard/graph_model.py tests/dashboard/test_build_graph_tree.py
git commit -m "test(demo-p1): verrous walk divisé — paire par niveau, court-circuit, récit de collecte"
```

---

### Task 8: Walk — chaîne D3 (diagnostic, EVAL v2, passe retry, origine division)

**Files:**
- Test: `tests/dashboard/test_build_graph_tree.py`
- Modify (si écart): `dashboard/graph_model.py`

- [ ] **Step 1: Écrire les tests D3**

Ajouter à `tests/dashboard/test_build_graph_tree.py` :

```python
class TestD3Walk:
    def test_route_agent_retry(self):
        events = (simple_pass("t1", success=False)
                  + [diag("t1", "ag", "agent", reason="weak", consignes="be precise")]
                  + simple_pass("t1", success=True, content="fixed"))
        graph = build_graph(events, meta("t1", "do it"))
        types = [(s.milestone_type, s.pass_index) for s in graph.steps]
        assert types == [("input", 0), ("tagger", 0),
                         ("dispatch", 0), ("agent", 0), ("evaluator", 0),
                         ("diagnostic", 0),
                         ("dispatch", 1), ("agent", 1), ("evaluator", 1),
                         ("output", 0)]
        dg = next(s for s in graph.steps if s.milestone_type == "diagnostic")
        assert dg.outcome == "diagnosed"
        assert dg.label == "DIAGNOSTIC · route agent"
        assert dg.detail.diagnostic.attribution == "agent"
        assert dg.detail.diagnostic.consignes == "be precise"
        # le loop-back diag→dispatch s'allume au DISPATCH pass 2
        d2 = next(s for s in graph.steps if s.milestone_type == "dispatch" and s.pass_index == 1)
        assert d2.label == "DISPATCH · pass 2"
        pairs = {(e.from_node, e.to, e.flow) for e in d2.active_edges}
        assert ("diagnostic:t1", "dispatch:t1", "transient") in pairs
        # l'output final vient de la passe 2
        assert graph.steps[-1].detail.output.output_content == "fixed"

    def test_route_evaluator_reeval_success(self):
        spec_v2 = EvaluatorSpec(criteria=[CriterionSpec(name="non_empty", gate=True)])
        events = (simple_pass("t1", success=False)
                  + [diag("t1", "ag", "evaluator", reason="strict"),
                     qa("t1", "ag", success=True, spec=spec_v2)])
        graph = build_graph(events, meta("t1", "do it"))
        types = [s.milestone_type for s in graph.steps]
        assert types == ["input", "tagger", "dispatch", "agent", "evaluator",
                         "diagnostic", "evaluator", "output"]
        v2 = [s for s in graph.steps if s.milestone_type == "evaluator"][1]
        assert v2.label == "EVALUATOR v2"
        assert v2.outcome == "qa_pass"
        assert v2.detail.evaluator.spec.criteria[0].name == "non_empty"   # spec régénérée
        v1 = [s for s in graph.steps if s.milestone_type == "evaluator"][0]
        assert v1.detail.evaluator.spec is None                            # specs v1/v2 distinctes
        # l'output final est l'output ORIGINAL (validé par la spec v2)
        assert graph.steps[-1].detail.output.output_content == "content"

    def test_route_evaluator_reeval_fail_then_retry(self):
        events = (simple_pass("t1", success=False)
                  + [diag("t1", "ag", "evaluator", consignes="clarify"), qa("t1", "ag", success=False)]
                  + simple_pass("t1", success=True, content="recovered"))
        graph = build_graph(events, meta("t1", "do it"))
        types = [s.milestone_type for s in graph.steps]
        assert types == ["input", "tagger", "dispatch", "agent", "evaluator",
                         "diagnostic", "evaluator",
                         "dispatch", "agent", "evaluator", "output"]
        assert graph.steps[-1].detail.output.output_content == "recovered"

    def test_route_task_spec_division_origin_diagnostic(self):
        events = (simple_pass("root", success=False)
                  + [diag("root", "ag", "task_spec", reason="ambiguous"),
                     divided("root", [("s1", "part A", [], {"python": 50}),
                                      ("s2", "part B", [], {"python": 50})])]
                  + simple_pass("s1") + simple_pass("s2")
                  + [aggregated("root", ["s1", "s2"])])
        graph = build_graph(events, meta("root", "big"))
        div = next(s for s in graph.steps if s.milestone_type == "divider")
        assert div.detail.divider.origin == "diagnostic"
        # l'arête de division part du DIAG, pas du dispatch
        flows = {(e.from_node, e.to): e.flow for e in graph.edges}
        assert flows[("diagnostic:root", "divider:root")] == "ascent"
        assert ("dispatch:root", "divider:root") not in flows
        # séquence : ... evaluator (fail) → diagnostic → divider → branches → aggregator → output
        types = [s.milestone_type for s in graph.steps]
        i = types.index("diagnostic")
        assert types[i + 1] == "divider"

    def test_route_unattributed_stops(self):
        events = simple_pass("t1", success=False) + [diag("t1", "ag", "unattributed", reason="")]
        graph = build_graph(events, meta("t1", "do it"))
        dg = graph.steps[-1]
        assert dg.milestone_type == "diagnostic"
        assert dg.label == "DIAGNOSTIC · route stop"
        assert dg.detail.diagnostic.route_taken == "stop"
        # pas d'output : la branche meurt au diagnostic
        assert all(s.milestone_type != "output" for s in graph.steps)

    def test_diagnostic_node_and_edges_static(self):
        events = (simple_pass("t1", success=False)
                  + [diag("t1", "ag", "agent", consignes="x")]
                  + simple_pass("t1", success=True))
        graph = build_graph(events, meta("t1", "do it"))
        ids = {n.id for n in graph.nodes}
        assert "diagnostic:t1" in ids
        n = next(n for n in graph.nodes if n.id == "diagnostic:t1")
        assert n.type == "diagnostic"
        flows = {(e.from_node, e.to): e.flow for e in graph.edges}
        assert flows[("evaluator:t1", "diagnostic:t1")] == "descent"
        assert flows[("diagnostic:t1", "dispatch:t1")] == "transient"
```

- [ ] **Step 2: Lancer, corriger jusqu'au PASS**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_build_graph_tree.py::TestD3Walk -v`
Expected: PASS après corrections éventuelles du walk (points sensibles : `EVALUATOR v2` émis dans
l'itération `pi == 0` ; `_division_origin` lit `run.diagnosed`).

- [ ] **Step 3: Commit**

```bash
git add dashboard/graph_model.py tests/dashboard/test_build_graph_tree.py
git commit -m "test(demo-p1): verrous chaîne D3 — diagnostic, EVAL v2, passe retry, origine division"
```

---

### Task 9: Walk — roster_gap (cul-de-sac) en contexte divisé

**Files:**
- Test: `tests/dashboard/test_build_graph_tree.py`
- Modify (si écart): `dashboard/graph_model.py`

- [ ] **Step 1: Écrire les tests roster_gap**

Ajouter à `tests/dashboard/test_build_graph_tree.py` :

```python
class TestRosterGap:
    def test_roster_gap_branch_is_dead_end(self):
        events = ([p1("root", "ag", passed=False),
                   UnassignedEvent(session_id=SID, task_id="root", reason="r"),
                   divided("root", [("s1", "ok", [], {"python": 50}),
                                    ("s2", "needs legal", [], {"legal": 50})])]
                  + simple_pass("s1")
                  + [RosterGapEvent(session_id=SID, task_id="s2", missing_tags=["legal"])])
        graph = build_graph(events, meta("root", "big"))
        # nœud terminal dédié, tags manquants en label
        gap = next(n for n in graph.nodes if n.type == "roster_gap")
        assert gap.id == "roster_gap:s2"
        assert "legal" in gap.label
        # riser depuis le divider, AUCUNE descente depuis le gap
        flows = {(e.from_node, e.to): e.flow for e in graph.edges}
        assert flows[("divider:root", "roster_gap:s2")] == "ascent"
        assert not any(frm == "roster_gap:s2" for (frm, _to) in flows)
        # jalon dédié, outcome roster_gap, detail porté
        gs = next(s for s in graph.steps if s.milestone_type == "roster_gap")
        assert gs.outcome == "roster_gap"
        assert gs.detail.roster_gap.missing_tags == ["legal"]
        assert gs.sub_task_id == "s2"
        # s1 unique sink → court-circuit → OUTPUT existe quand même
        assert graph.steps[-1].milestone_type == "output"

    def test_roster_gap_at_root(self):
        events = [RosterGapEvent(session_id=SID, task_id="t1", missing_tags=["legal", "gdpr"])]
        graph = build_graph(events, meta("t1", "do it"))
        types = [s.milestone_type for s in graph.steps]
        assert types == ["input", "tagger", "roster_gap"]
        assert graph.steps[-1].detail.roster_gap.missing_tags == ["legal", "gdpr"]
```

- [ ] **Step 2: Lancer, corriger jusqu'au PASS**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_build_graph_tree.py::TestRosterGap -v`
Expected: PASS (le walk Task 6 gère déjà le cul-de-sac ; vérifier que `_build_structure` n'émet
aucune arête sortante du gap).

- [ ] **Step 3: Commit**

```bash
git add dashboard/graph_model.py tests/dashboard/test_build_graph_tree.py
git commit -m "test(demo-p1): verrous roster_gap — nœud terminal, riser, aucune descente"
```

---

### Task 10: TODO hiérarchique (post-processing backend)

La TODO devient un calcul a posteriori sur la liste de jalons : items révélés au DIVIDER de leur
parent, `parent_id`/`depth` depuis l'arbre, `first_step_index` = premier jalon de la tâche
(le calcul JS `firstStepIndexForTask` migre ici), `note` = annotation de marge.

**Files:**
- Modify: `dashboard/graph_model.py`
- Test: `tests/dashboard/test_build_graph_tree.py`

- [ ] **Step 1: Écrire les tests TODO**

Ajouter à `tests/dashboard/test_build_graph_tree.py` :

```python
class TestTodoHierarchy:
    def test_simple_run_root_only(self):
        graph = build_graph(simple_pass("t1"), meta("t1", "do it"))
        first, last = graph.steps[0].todo, graph.steps[-1].todo
        assert len(first) == 1 and first[0].is_root and first[0].state == "current"
        assert first[0].depth == 0 and first[0].parent_id is None
        assert first[0].first_step_index == 0
        assert last[0].state == "done"

    def test_subtasks_revealed_at_divider_with_hierarchy(self):
        graph = build_graph(divided_agg_fixture(), meta("root", "big"))
        before = next(s for s in graph.steps if s.milestone_type == "dispatch" and s.sub_task_id == "root")
        assert [t.id for t in before.todo] == ["root"]
        div = next(s for s in graph.steps if s.milestone_type == "divider")
        items = {t.id: t for t in div.todo}
        assert set(items) == {"root", "s1", "s2"}
        assert items["s1"].parent_id == "root" and items["s1"].depth == 1
        assert items["s1"].state == "pending" and items["s2"].state == "pending"

    def test_states_progress_and_navigation(self):
        graph = build_graph(divided_agg_fixture(), meta("root", "big"))
        d1 = next(i for i, s in enumerate(graph.steps)
                  if s.milestone_type == "dispatch" and s.sub_task_id == "s1")
        states = {t.id: t.state for t in graph.steps[d1].todo}
        assert states == {"root": "current", "s1": "current", "s2": "pending"}
        # navigation : first_step_index pointe le premier jalon de la tâche
        item_s1 = next(t for t in graph.steps[d1].todo if t.id == "s1")
        assert item_s1.first_step_index == d1
        # à l'output : tout done
        assert {t.state for t in graph.steps[-1].todo} == {"done"}

    def test_nested_depths(self):
        events = (
            [p1("root", "ag", passed=False), UnassignedEvent(session_id=SID, task_id="root", reason="r"),
             divided("root", [("c1", "part 1", [], {"python": 50}), ("c2", "part 2", [], {"python": 50})])]
            + [p1("c1", "ag", passed=False), UnassignedEvent(session_id=SID, task_id="c1", reason="r"),
               divided("c1", [("g1", "deep A", [], {"python": 50})])]
            + simple_pass("g1") + simple_pass("c2")
            + [aggregated("root", ["c1", "c2"])]
        )
        graph = build_graph(events, meta("root", "big"))
        last = {t.id: t for t in graph.steps[-1].todo}
        assert last["g1"].depth == 2 and last["g1"].parent_id == "c1"
        # g1 n'apparaît qu'à partir du DIVIDER de c1
        div_c1 = next(i for i, s in enumerate(graph.steps)
                      if s.milestone_type == "divider" and s.sub_task_id == "c1")
        assert all("g1" not in {t.id for t in s.todo} for s in graph.steps[:div_c1])

    def test_notes_annotations(self):
        # retry → note "pass 2" + route ; roster gap → note "roster gap"
        events = ([p1("root", "ag", passed=False),
                   UnassignedEvent(session_id=SID, task_id="root", reason="r"),
                   divided("root", [("s1", "retry me", [], {"python": 50}),
                                    ("s2", "needs legal", [], {"legal": 50})])]
                  + simple_pass("s1", success=False)
                  + [diag("s1", "ag", "agent", consignes="x")]
                  + simple_pass("s1", success=True)
                  + [RosterGapEvent(session_id=SID, task_id="s2", missing_tags=["legal"])])
        graph = build_graph(events, meta("root", "big"))
        last = {t.id: t for t in graph.steps[-1].todo}
        assert "pass 2" in last["s1"].note and "route agent" in last["s1"].note
        assert last["s2"].note == "roster gap"
        assert last["s2"].state == "failed"

    def test_failed_states(self):
        # qa_fail final (diag unattributed) → failed
        events = simple_pass("t1", success=False) + [diag("t1", "ag", "unattributed", reason="")]
        graph = build_graph(events, meta("t1", "do it"))
        assert graph.steps[-1].todo[0].state == "failed"
```

- [ ] **Step 2: Lancer, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_build_graph_tree.py::TestTodoHierarchy -v`
Expected: FAIL (`todo == []` partout).

- [ ] **Step 3: Implémenter `_attach_todos`**

Ajouter dans `dashboard/graph_model.py` :

```python
def _attach_todos(steps: list[GraphStep], tree: _Tree, runs: dict[str, _TaskRun]) -> None:
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
```

Appeler en fin de `_build_steps`, juste avant le `return steps` :

```python
    _attach_todos(steps, tree, runs)
    return steps
```

- [ ] **Step 4: Lancer, vérifier le PASS (toute la suite tree)**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_build_graph_tree.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dashboard/graph_model.py tests/dashboard/test_build_graph_tree.py
git commit -m "feat(demo-p1): TODO hiérarchique backend — révélation, depth, navigation, notes"
```

---

### Task 11: Migration des suites existantes + collectors + suite complète

Le contrat API a cassé (IDs namespacés, tagger, testset retiré). Cette task remet TOUTE la suite au vert.

**Files:**
- Modify: `tests/dashboard/test_build_graph_milestones.py`, `test_build_graph_a4.py`,
  `test_build_graph_d2.py`, `test_graph_model.py`, `test_serialization.py`,
  `test_collectors_sessions.py`, `test_collectors_health_checks.py`, `test_api.py` (si besoin)
- Verify: `dashboard/collectors/sessions.py`, `dashboard/collectors/health_checks.py` (signatures inchangées)

- [ ] **Step 1: Lancer la suite dashboard, lister les échecs**

Run: `.venv\Scripts\python -m pytest tests/dashboard/ -q`
Expected: échecs concentrés sur les fichiers ci-dessus. Lire chaque échec avant de toucher.

- [ ] **Step 2: Migrer `test_build_graph_milestones.py`**

Règles de migration mécaniques (appliquer à chaque assertion) :

| Ancien | Nouveau |
| --- | --- |
| `"dispatch"` (node id) | `"dispatch:<tid>"` (tid de la fixture : `t1`, `s1`, `parent`…) |
| `"evaluator"` | `"evaluator:<tid>"` |
| `"ag"` (node id agent) | `"agent:<tid>:ag"` |
| `_tool_node_id("grep")` / `"tool:grep"` | `"tool:<tid>:grep"` |
| `"divider"` / `"aggregator"` | `"divider:<parent>"` / `"aggregator:<parent>"` |
| séquence `["input", "dispatch", ...]` | + `"tagger"` après `"input"` UNIQUEMENT si la meta porte des `required_tags` |
| assertions `testset` (nœud/arête) | SUPPRIMER (le nœud a disparu ; `detail.testset` reste) |
| `from dashboard.graph_model import _build_nodes, _build_edges, _tool_node_id` | supprimer — tester via `build_graph(...).nodes/.edges` |

Concrètement : les classes `TestNodes`/`TestEdges` (qui appelaient `_build_nodes`/`_build_edges`
avec des events nus, sans arbre) sont SUPPRIMÉES — couvertes par `TestStructure` de la nouvelle
suite. Les classes de jalons (`TestSimpleRunMilestones`, `TestToolMilestones`,
`TestDividedRunMilestones`, `TestTodoSimple`, `TestTodoDivided`, `TestFailAndUnassignedStates`,
`TestRealDividedTrace` et équivalents D2) migrent par les règles ci-dessus. Attention au test
trace réelle (`skipif`) : la session réelle a des `required_tags` → la séquence commence
`["input", "tagger", "divider"...]`... non : `["input", "tagger", "dispatch", ...]` n'apparaît
que si la racine a une passe ; pour la trace `run_demo_v3` (racine pinned → run_task → unassigned
→ divided), la séquence attendue devient `types[0] == "input"`, `"divider" in types`,
`types[-1] == "output"` — assouplir ce test à ces invariants plutôt qu'une séquence exacte.

- [ ] **Step 3: Migrer `test_build_graph_a4.py` et `test_build_graph_d2.py`**

Mêmes règles. Points spécifiques D2 : le court-circuit single-sink reste : pas de nœud
`aggregator:<parent>`, OUTPUT terminal depuis le sink ; `collected`/`total` comptent les sinks
(assertions conservées, IDs namespacés).

- [ ] **Step 4: Migrer `test_graph_model.py` et `test_serialization.py`**

`test_graph_model.py` : les helpers/fixtures restent ; les tests de builder migrés ou supprimés
s'ils dupliquent la suite tree. `test_serialization.py` : étendre le test divisé existant :

```python
def test_tree_graph_serializes_with_flow_and_tasks():
    from tests.dashboard.test_build_graph_tree import divided_agg_fixture, meta
    from dashboard.graph_model import build_graph
    graph = build_graph(divided_agg_fixture(), meta("root", "big"))
    dumped = graph.model_dump(by_alias=True, mode="json")
    assert all("from" in e and "flow" in e for e in dumped["edges"])
    assert {t["id"] for t in dumped["tasks"]} == {"root", "s1", "s2"}
    assert all("pass_index" in s for s in dumped["steps"])
    todo = dumped["steps"][-1]["todo"]
    assert all("first_step_index" in t and "depth" in t for t in todo)
```

- [ ] **Step 5: Collectors — vérifier, adapter les assertions**

`dashboard/collectors/sessions.py` et `health_checks.py` appellent `build_graph(events, meta)` —
signature inchangée, rien à modifier côté collectors. Adapter les assertions de leurs tests aux
nouveaux invariants (`milestone_type`, IDs namespacés). Pour le case-graph health (single-task) :
séquence dégénérée `["input", ("tagger" si tags), "dispatch", ..., "evaluator"|"output"]`.

- [ ] **Step 6: Suite complète**

Run: `.venv\Scripts\python -m pytest -q`
Expected: PASS complet (822 existants migrés + ~55 nouveaux ; zéro régression hors dashboard).

- [ ] **Step 7: Commit**

```bash
git add tests/dashboard dashboard
git commit -m "test(demo-p1): migration suites graphe vers le contrat arbre namespacé"
```

---

## PARTIE C — Frontend (sous `/impeccable`, hors TDD auto)

**Discipline `/impeccable` (demande explicite de Quentin, spec §6.2)** : au DÉBUT de chaque task de
cette partie, invoquer le skill `/impeccable` (sans sous-commande : invocation générale, register
**product**, contexte `DESIGN.md`/`PRODUCT.md` chargé par le loader). Les lois du skill s'appliquent :
un seul héros chaud (`--fire`), `--crest` famille chaude (PAS de nouvelle teinte), pas de glow décoratif,
motion = état uniquement, bans absolus (pas de side-stripe, pas de gradient text). La Task 17 passe
`/impeccable critique` puis `/impeccable polish` sur le tab Sessions avant le sign-off.

Validation = navigateur sur contrat API live (pattern V2c). Le code ci-dessous est le point de départ
complet ; l'itération visuelle (espacements, chanfreins, rythme) se fait en navigateur sous le skill —
`/impeccable live` est disponible si l'itération fine l'exige.

### Task 12: `graph.js` — layout arbre bottom-up + routage delta 45° + flow colors + badge ×N

**Files:**
- Rewrite: `dashboard/static/js/graph.js`

- [ ] **Step 1: Invoquer `/impeccable`** (register product ; vérifier que DESIGN.md/PRODUCT.md sont chargés)

- [ ] **Step 2: Réécrire `graph.js`**

Remplacer intégralement le contenu par :

```javascript
// graph.js — arbre émergent bottom-up (série D). Racines (INPUT/TAGGER/OUTPUT) en bas,
// l'arbre pousse vers le haut : une arche par branche (DISPATCH montée → AGENT apex → EVAL descente),
// paire DIVIDER/AGGREGATOR par niveau, routage delta 45° (rails + chanfreins, point = jonction).
const SVG_NS = "http://www.w3.org/2000/svg";
const NODE_W = 104, NODE_H = 40;
const ROW_H = 96;        // pas vertical de la grille (k-rows)
const SLOT_W = 244;      // largeur d'un slot de branche feuille
const LEG_IN = 56;       // retrait des jambes (montée/descente) depuis les bords du slot
const PAD = 64;
const CH = 14;           // chanfrein 45° aux coudes (dialecte delta)

const HEX_PTS = `${NODE_W / 2},0 ${NODE_W / 4},${NODE_H / 2} ${-NODE_W / 4},${NODE_H / 2} ${-NODE_W / 2},0 ${-NODE_W / 4},${-NODE_H / 2} ${NODE_W / 4},${-NODE_H / 2}`;
const DIA_PTS = `0,${-NODE_H / 2 - 4} ${NODE_W / 3},0 0,${NODE_H / 2 + 4} ${-NODE_W / 3},0`; // losange DIAG

let hexSeq = 0;

function el(name, attrs = {}) {
  const e = document.createElementNS(SVG_NS, name);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  return e;
}

const fmt = n => Math.round(n * 10) / 10;

// ---------------------------------------------------------------- arbre
function buildTree(graph) {
  const tasks = graph.tasks || [];
  const byId = {}, kids = {};
  let root = null;
  for (const t of tasks) {
    byId[t.id] = t;
    if (t.parent_id == null) root = t.id;
    else (kids[t.parent_id] ||= []).push(t);
  }
  for (const k in kids) kids[k].sort((a, b) => a.order_index - b.order_index);
  return { byId, root, children: id => (kids[id] || []).map(t => t.id) };
}

// ---------------------------------------------------------------- layout
// k-rows depuis le bas : 0 = racines (INPUT/OUTPUT), 1 = TAGGER (tronc).
// Tâche de profondeur d : organes (DISPATCH/EVAL/GAP) k=2d+2, apex (AGENT ou paire
// DIVIDER/AGGREGATOR) k=2d+3, canopée TOOLS k=2d+4. DIAG s'insère sur la jambe de
// descente entre l'organe et la rangée du dessous.
function layout(graph) {
  const tree = buildTree(graph);
  const byTask = {};
  for (const n of graph.nodes) {
    if (!n.task_id) continue;
    const b = (byTask[n.task_id] ||= { agents: [], tools: [] });
    if (n.type === "agent") b.agents.push(n);
    else if (n.type === "tool") b.tools.push(n);
    else b[n.type] = n;
  }

  const span = {};
  let nextSlot = 0;
  (function place(tid) {
    const ks = tree.children(tid);
    if (!ks.length) {
      const x0 = PAD + nextSlot * SLOT_W;
      span[tid] = [x0, x0 + SLOT_W];
      nextSlot++;
      return;
    }
    for (const k of ks) place(k);
    span[tid] = [span[ks[0]][0], span[ks[ks.length - 1]][1]];
  })(tree.root);

  let maxK = 4;
  for (const t of (graph.tasks || [])) maxK = Math.max(maxK, 2 * t.depth + 4);
  const width = Math.max(PAD * 2 + nextSlot * SLOT_W, PAD * 2 + SLOT_W);
  const height = PAD * 2 + maxK * ROW_H + NODE_H;
  const Y = k => height - PAD - NODE_H / 2 - k * ROW_H;

  const pos = {};
  const [rx0, rx1] = span[tree.root] || [PAD, PAD + SLOT_W];
  pos.input = { cx: rx0 + LEG_IN, cy: Y(0) };
  pos.output = { cx: rx1 - LEG_IN, cy: Y(0) };
  pos.tagger = { cx: rx0 + LEG_IN, cy: Y(1) };

  for (const tid in byTask) {
    const t = tree.byId[tid];
    const sp = span[tid];
    if (!t || !sp) continue;
    const [x0, x1] = sp;
    const ax = x0 + LEG_IN, dx = x1 - LEG_IN, cx = (x0 + x1) / 2;
    const kOrg = 2 * t.depth + 2;
    const b = byTask[tid];
    if (b.dispatch) pos[b.dispatch.id] = { cx: ax, cy: Y(kOrg) };
    if (b.evaluator) pos[b.evaluator.id] = { cx: dx, cy: Y(kOrg) };
    if (b.diagnostic) pos[b.diagnostic.id] = { cx: dx, cy: Y(kOrg) + ROW_H * 0.58 };
    if (b.roster_gap) pos[b.roster_gap.id] = { cx: cx, cy: Y(kOrg) };
    b.agents.forEach((n, i) => {
      const off = (i - (b.agents.length - 1) / 2) * (NODE_W + 14);
      pos[n.id] = { cx: cx + off, cy: Y(kOrg + 1) };
    });
    b.tools.forEach((n, i) => {
      const innerW = Math.max(x1 - x0 - LEG_IN * 2, NODE_W);
      const step = b.tools.length > 1 ? innerW / (b.tools.length - 1) : 0;
      pos[n.id] = { cx: b.tools.length > 1 ? x0 + LEG_IN + i * step : cx, cy: Y(kOrg + 2) };
    });
    if (b.divider) pos[b.divider.id] = { cx: x0 + NODE_W / 2 + 4, cy: Y(kOrg + 1) };
    if (b.aggregator) pos[b.aggregator.id] = { cx: x1 - NODE_W / 2 - 4, cy: Y(kOrg + 1) };
  }
  return { pos, width, height };
}

// ---------------------------------------------------------------- routage delta 45°
// Convention schéma électrique : point = jonction réelle ; croisement sans point = rien.
function straight(a, b) { return { d: `M${fmt(a.cx)},${fmt(a.cy)} L${fmt(b.cx)},${fmt(b.cy)}`, dots: [] }; }

function railThenRise(a, b) {
  // rail horizontal à hauteur de a, chanfrein 45°, verticale vers b (bus d'émission, loop-backs)
  if (Math.abs(a.cx - b.cx) < CH * 2) return straight(a, b);
  const sx = Math.sign(b.cx - a.cx), sy = Math.sign(b.cy - a.cy) || -1;
  const jx = b.cx - sx * CH;
  return {
    d: `M${fmt(a.cx)},${fmt(a.cy)} L${fmt(jx)},${fmt(a.cy)} L${fmt(b.cx)},${fmt(a.cy + sy * CH)} L${fmt(b.cx)},${fmt(b.cy)}`,
    dots: [{ x: jx, y: a.cy }],
  };
}

function riseThenRail(a, b) {
  // verticale depuis a, chanfrein 45°, rail horizontal à hauteur de b (bus de collecte, montées vers divider)
  if (Math.abs(a.cy - b.cy) < CH * 2) return straight(a, b);
  const sx = Math.sign(b.cx - a.cx) || -1, sy = Math.sign(b.cy - a.cy);
  const jy = b.cy - sy * CH;
  return {
    d: `M${fmt(a.cx)},${fmt(a.cy)} L${fmt(a.cx)},${fmt(jy)} L${fmt(a.cx + sx * CH)},${fmt(b.cy)} L${fmt(b.cx)},${fmt(b.cy)}`,
    dots: [{ x: a.cx + sx * CH, y: b.cy }],
  };
}

function routeEdge(e, pos, typeById) {
  const a = pos[e.from], b = pos[e.to];
  if (!a || !b) return null;
  const tf = typeById[e.from], tt = typeById[e.to];
  if (tf === "divider" || tf === "diagnostic") return railThenRise(a, b);
  if (tt === "divider" || tt === "aggregator" || tt === "output") return riseThenRail(a, b);
  return straight(a, b);   // tronc, dispatch→agent (diagonale), agent→eval, agent→tool, eval→diag
}

// ---------------------------------------------------------------- état actif
function edgeKey(e) { return `${e.from}->${e.to}`; }

function unionActive(graph) {
  // union cumulée de tous les jalons (vue statique du health tab)
  const nodes = new Set(), edges = new Set();
  let winnerId = null, failBranch = false;
  for (const s of graph.steps) {
    s.active_nodes.forEach(n => nodes.add(n));
    s.active_edges.forEach(e => edges.add(edgeKey(e)));
    if (s.winner_agent_id) winnerId = s.winner_agent_id;
    if (s.outcome === "qa_fail") failBranch = true;
  }
  return { activeNodes: nodes, activeEdges: edges, winnerId, failBranch };
}

export function bboxOf(ids, pos) {
  const xs = [], ys = [];
  for (const id of ids) { const p = pos[id]; if (p) { xs.push(p.cx); ys.push(p.cy); } }
  if (!xs.length) return null;
  const x0 = Math.min(...xs) - NODE_W, x1 = Math.max(...xs) + NODE_W;
  const y0 = Math.min(...ys) - NODE_H * 2, y1 = Math.max(...ys) + NODE_H * 2;
  return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
}

// ---------------------------------------------------------------- rendu
export function renderGraph(svg, graph, activeStepIndex, onNodeClick, agentNames = {}, opts = {}) {
  while (svg.firstChild) svg.removeChild(svg.firstChild);
  svg.setAttribute("class", "graph");

  const { pos, width, height } = layout(graph);
  if (!opts.keepViewBox) {
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
  }

  const hexId = `hex-${hexSeq}`, diaId = `dia-${hexSeq}`;
  hexSeq++;
  const defs = el("defs");
  defs.appendChild(el("polygon", { id: hexId, points: HEX_PTS }));
  defs.appendChild(el("polygon", { id: diaId, points: DIA_PTS }));
  svg.appendChild(defs);

  const typeById = Object.fromEntries(graph.nodes.map(n => [n.id, n.type]));

  const step = graph.steps[activeStepIndex] || null;
  let activeNodes, activeEdges, winnerId, failBranch;
  if (opts.fullPath) {
    const u = unionActive(graph);
    activeNodes = u.activeNodes; activeEdges = u.activeEdges;
    winnerId = u.winnerId; failBranch = u.failBranch;
  } else {
    activeNodes = new Set(step ? step.active_nodes : []);
    activeEdges = new Set(step ? step.active_edges.map(edgeKey) : []);
    winnerId = step ? step.winner_agent_id : null;
    failBranch = step && step.outcome === "qa_fail";
  }

  // arêtes : idle wire ; actives par flow (montée crest, descente fire, transient pointillé)
  const edgeLayer = el("g");
  const dotLayer = el("g");
  const pulseLayer = el("g");
  let pulseIdx = 0;
  for (const e of graph.edges) {
    const r = routeEdge(e, pos, typeById);
    if (!r) continue;
    const isActive = activeEdges.has(edgeKey(e));
    const path = el("path", { d: r.d, class: `edge edge--${e.flow}${isActive ? " edge--a" : ""}` });
    edgeLayer.appendChild(path);
    for (const dot of r.dots) {
      dotLayer.appendChild(el("circle", {
        cx: fmt(dot.x), cy: fmt(dot.y), r: 2.4,
        class: "junction" + (isActive ? " junction--a" : ""),
      }));
    }
    // pulses directionnels : points crest montent, points ember descendent (jamais sur transient)
    if (isActive && e.flow !== "transient") {
      const dot = el("circle", { r: 2.8, class: `pulse pulse--${e.flow}` });
      const motion = el("animateMotion", {
        dur: "2.6s",
        begin: (pulseIdx++ * 0.7).toFixed(1) + "s",
        repeatCount: "indefinite",
        path: r.d,
      });
      dot.appendChild(motion);
      pulseLayer.appendChild(dot);
    }
  }
  svg.appendChild(edgeLayer);
  svg.appendChild(dotLayer);
  svg.appendChild(pulseLayer);

  // badge ×N : même agent réel instancié sur plusieurs branches
  const instances = {};
  for (const n of graph.nodes) if (n.type === "agent" && n.agent_id) (instances[n.agent_id] ||= []).push(n.id);

  for (const n of graph.nodes) {
    const p = pos[n.id];
    if (!p) continue;
    const g = el("g", { class: "node node--" + n.type, transform: `translate(${fmt(p.cx)},${fmt(p.cy)})` });
    g.dataset.nodeId = n.id;
    if (n.agent_id) g.dataset.agentId = n.agent_id;
    if (activeNodes.has(n.id)) g.classList.add("node--active");
    if (n.agent_id && n.agent_id === winnerId && activeNodes.has(n.id)) g.classList.add("node--winner");

    const shapeRef = n.type === "diagnostic" ? diaId : hexId;
    const shape = el("use", { class: "hex", href: "#" + shapeRef });
    shape.setAttributeNS("http://www.w3.org/1999/xlink", "href", "#" + shapeRef);
    const label = el("text", { x: 0, y: 4, "text-anchor": "middle", class: "node-label" });
    label.textContent = (n.type === "agent" && agentNames[n.agent_id]) || n.label;
    g.append(shape, label);

    const kin = n.agent_id ? instances[n.agent_id] : null;
    if (kin && kin.length > 1) {
      const badge = el("text", { x: NODE_W / 2 - 6, y: -NODE_H / 2 + 2, "text-anchor": "end", class: "node-badge" });
      badge.textContent = `×${kin.length}`;
      g.appendChild(badge);
      g.addEventListener("mouseenter", () => {
        svg.querySelectorAll(`[data-agent-id="${n.agent_id}"]`).forEach(x => x.classList.add("node--kin"));
      });
      g.addEventListener("mouseleave", () => {
        svg.querySelectorAll(".node--kin").forEach(x => x.classList.remove("node--kin"));
      });
    }
    if (onNodeClick) g.addEventListener("click", () => onNodeClick(n, step));
    svg.appendChild(g);
  }
  return { pos, width, height };
}
```

Points de design verrouillés portés par ce code : bottom-up via `Y(k)` inversé ; arche = diagonales
naturelles dispatch→agent→eval (jambes aux bords du slot, apex centré) ; paire divider (gauche) /
aggregator (droite) aux bords du span ; bus = `railThenRise`/`riseThenRail` avec chanfrein 45° et
**point de jonction** ; couleur par flow via classes CSS (Task 14) ; direction redondante par pulses.
Le tier `winnerId` : un nœud agent n'est winner que si actif (les instances ×N ne brûlent pas toutes).

- [ ] **Step 3: Vérification statique rapide**

Run: `.venv\Scripts\python -m dashboard` → http://localhost:5000, tab Sessions, sélectionner une
session persistée. Le graphe doit se dessiner sans erreur console (les couleurs/CSS arrivent en
Task 14 — l'arbre peut être terne, c'est attendu). Vérifier : racines en bas, arches, divider/aggregator
aux bords, points de jonction sur les rails.

- [ ] **Step 4: Commit**

```bash
git add dashboard/static/js/graph.js
git commit -m "feat(demo-p1): graphe arbre bottom-up — layout k-rows, routage delta 45°, badge ×N"
```

---

### Task 13: `camera.js` — zoom ancré curseur, drag pan, follow-mode débrayable

**Files:**
- Create: `dashboard/static/js/camera.js`

- [ ] **Step 1: Invoquer `/impeccable`** (si session différente de la Task 12)

- [ ] **Step 2: Créer `camera.js`**

```javascript
// camera.js — caméra viewBox du graphe Sessions : zoom molette ancré au curseur,
// drag pan, follow-mode débrayable (auto-centrage ~250ms ease-out sur le jalon actif).
// Aucune lib : transform sur le viewBox SVG. Toute interaction manuelle suspend le follow.
const EASE = t => 1 - Math.pow(1 - t, 4);   // ease-out-quart

export function attachCamera(svg, { onManual } = {}) {
  let content = { width: 1, height: 1 };
  let vb = null;             // {x, y, w, h}
  let follow = true;
  let anim = null;

  const apply = () => svg.setAttribute("viewBox", `${vb.x} ${vb.y} ${vb.w} ${vb.h}`);

  function setContent(width, height) {
    content = { width, height };
    if (vb === null) reset();   // auto-fit au chargement
    else apply();               // re-render : cadrage courant conservé
  }

  function reset() {
    vb = { x: 0, y: 0, w: content.width, h: content.height };
    apply();
  }

  function svgPoint(ev) {
    const r = svg.getBoundingClientRect();
    return {
      x: vb.x + ((ev.clientX - r.left) / r.width) * vb.w,
      y: vb.y + ((ev.clientY - r.top) / r.height) * vb.h,
    };
  }

  function manual() {
    if (anim) { cancelAnimationFrame(anim); anim = null; }
    if (follow) { follow = false; if (onManual) onManual(); }
  }

  svg.addEventListener("wheel", (ev) => {
    ev.preventDefault();
    manual();
    const p = svgPoint(ev);
    const f = ev.deltaY > 0 ? 1.18 : 1 / 1.18;
    const w = Math.min(Math.max(vb.w * f, content.width * 0.08), content.width * 2.5);
    const h = w * (vb.h / vb.w);
    vb = { x: p.x - (p.x - vb.x) * (w / vb.w), y: p.y - (p.y - vb.y) * (h / vb.h), w, h };
    apply();
  }, { passive: false });

  let drag = null;
  svg.addEventListener("pointerdown", (ev) => {
    if (ev.target.closest(".node")) return;   // ne pas voler le clic des nœuds
    drag = { x: ev.clientX, y: ev.clientY, vb: { ...vb } };
    svg.setPointerCapture(ev.pointerId);
  });
  svg.addEventListener("pointermove", (ev) => {
    if (!drag) return;
    manual();
    const r = svg.getBoundingClientRect();
    vb.x = drag.vb.x - (ev.clientX - drag.x) * (vb.w / r.width);
    vb.y = drag.vb.y - (ev.clientY - drag.y) * (vb.h / r.height);
    apply();
  });
  ["pointerup", "pointercancel"].forEach(t => svg.addEventListener(t, () => { drag = null; }));

  function tween(target, ms = 250) {
    if (anim) cancelAnimationFrame(anim);
    const from = { ...vb }, t0 = performance.now();
    const stepFn = (now) => {
      const t = Math.min(1, (now - t0) / ms), k = EASE(t);
      vb = {
        x: from.x + (target.x - from.x) * k, y: from.y + (target.y - from.y) * k,
        w: from.w + (target.w - from.w) * k, h: from.h + (target.h - from.h) * k,
      };
      apply();
      anim = t < 1 ? requestAnimationFrame(stepFn) : null;
    };
    anim = requestAnimationFrame(stepFn);
  }

  function focusOn(bbox, { margin = 110 } = {}) {
    if (!follow || !bbox || vb === null) return;
    const ratio = vb.h / vb.w;
    let w = Math.max(bbox.w + margin * 2, content.width * 0.32);
    let h = Math.max(bbox.h + margin * 2, w * ratio);
    if (h / w > ratio) w = h / ratio; else h = w * ratio;
    tween({ x: bbox.x + bbox.w / 2 - w / 2, y: bbox.y + bbox.h / 2 - h / 2, w, h });
  }

  function setFollow(v) {
    follow = v;
  }

  return { setContent, reset, focusOn, setFollow, isFollowing: () => follow };
}
```

- [ ] **Step 3: Commit**

```bash
git add dashboard/static/js/camera.js
git commit -m "feat(demo-p1): caméra graphe — zoom ancré curseur, pan, follow-mode débrayable"
```

---

### Task 14: CSS — flow colors, nœuds DIAG/GAP, jonctions, TODO, bouton ⌖ + amendement DESIGN.md

**Files:**
- Modify: `dashboard/static/css/` (repérer le fichier portant `.edge`, `.node--*`, `.todo-item`, `.pulse`)
- Modify: `DESIGN.md`

- [ ] **Step 1: Invoquer `/impeccable`**, puis repérer le CSS courant

Run: `.venv\Scripts\python -c "import pathlib; print([p.name for p in pathlib.Path('dashboard/static/css').glob('*.css')])"`
Lire le fichier portant `.edge`/`.node--agent`/`.todo-item` AVANT d'écrire (réutiliser les tokens,
les sélecteurs existants, l'ordre des sections). Supprimer le bloc `.gtier`/tier labels s'il existe
encore (les bandes globales ont disparu).

- [ ] **Step 2: Ajouter/adapter les styles**

En réutilisant STRICTEMENT les tokens existants (aucune nouvelle teinte — anti-slop DESIGN.md) :

```css
/* ---- arêtes par flow : montée crest, descente fire, transient pointillé ---- */
.edge { stroke: var(--wire); fill: none; stroke-width: 1; }
.edge--transient { stroke-dasharray: 4 4; }
.edge--a { stroke-width: 1.4; }
.edge--a.edge--ascent { stroke: var(--crest); }
.edge--a.edge--descent { stroke: var(--fire-2); filter: drop-shadow(0 0 3px var(--fire-glow)); }
.edge--a.edge--transient { stroke: var(--wire-2); }

/* jonctions (point = contact réel, convention schéma électrique) */
.junction { fill: var(--wire); }
.junction--a { fill: var(--fg-1); }

/* pulses directionnels (redondance de la couleur, jamais seuls porteurs du sens) */
.pulse--ascent { fill: var(--crest); }
.pulse--descent { fill: var(--fire); filter: drop-shadow(0 0 4px var(--fire-glow)); }

/* ---- nouveaux nœuds ---- */
.node--diagnostic .hex { stroke: var(--warn); }
.node--diagnostic.node--active .hex { stroke: var(--warn); filter: drop-shadow(0 0 4px var(--warn)); }
.node--diagnostic .node-label { fill: var(--warn); }
.node--roster_gap .hex { stroke: var(--fail); }
.node--roster_gap .node-label { fill: var(--fail); }
.node--roster_gap.node--active .hex { filter: drop-shadow(0 0 4px var(--fail)); }
.node--tagger .hex { stroke-dasharray: 3 3; }

/* badge ×N + hover toutes-instances d'un agent */
.node-badge { font-size: 9px; fill: var(--fg-2); }
.node--kin .hex { stroke: var(--wire-2); }

/* ---- TODO hiérarchique : note de marge (l'indentation par depth est inline, JS) ---- */
.todo-note { margin-left: auto; font-size: 10px; color: var(--fg-2); white-space: nowrap; }
.todo--failed .todo-note { color: var(--fail); }

/* ---- bouton follow ⌖ (coin du graph-frame) ---- */
.follow-btn {
  position: absolute; top: 8px; right: 10px; z-index: 2;
  background: var(--bg-2); border: 1px solid var(--wire); color: var(--fg-1);
  font: 11px var(--mono, monospace); padding: 3px 8px; cursor: pointer;
  transition: color 160ms, border-color 160ms;
}
.follow-btn.on { color: var(--fire); border-color: var(--wire-2); }
.graph-frame { position: relative; }
```

Adapter les sélecteurs aux noms réels du fichier (ex. si les arêtes actives utilisaient `.edge--a`
en `<line>`, le passage en `<path>` ne change pas les sélecteurs ; si `.edge--fail` existait pour
testset, le supprimer avec son markup).

- [ ] **Step 3: Amender `DESIGN.md`**

Dans la section **Color (OKLCH)**, remplacer la ligne de `--crest` :

```
--crest:    oklch(82% 0.04 70)     /* wave crest, winner label, graph ascent edges */
```

Dans la section **Motion**, remplacer la ligne « Graph live path » par :

```
- **Graph live path**: directional **pulse dots** travel the active edges (`<animateMotion>`, ~2.6s,
  staggered) — crest dots climb the ascent legs, ember dots ride the descents; the winner node
  **burns steady** (no blink). Direction is never carried by color alone. Idle edges/nodes are still.
```

Dans la section **Components**, ligne « Hex graph », remplacer par :

```
- **Hex graph**: bottom-up emergent tree (roots I/O at the bottom, one arch per branch:
  DISPATCH ascent → AGENT apex with tool canopy → EVAL descent; a DIVIDER/AGGREGATOR pair frames
  each level). Delta-45 routing: horizontal bus rails + 45deg chamfers, junction dot = real contact.
  Ascent edges `--crest`, descents `--fire-2`, transients dashed wire. DIAG is a `--warn` diamond
  on the descent; ROSTER GAP a `--fail` dead-end. Camera: cursor-anchored zoom + pan,
  defeatable follow-mode. The `--cool` reserve (charts only) is unchanged.
```

- [ ] **Step 4: Vérifier navigateur**

Dashboard ouvert : montées crest / descentes ember sur les jalons actifs, jonctions visibles,
DIAG losange warn, GAP fail (si fixtures présentes), pas de glow sur le chrome statique.

- [ ] **Step 5: Commit**

```bash
git add dashboard/static/css DESIGN.md
git commit -m "feat(demo-p1): colorway crest→fire, nœuds DIAG/GAP, jonctions delta, amendement DESIGN.md"
```

---

### Task 15: `modal.js` — DIAG, ROSTER GAP, TAGGER, divider origine, evaluator pass-aware

**Files:**
- Modify: `dashboard/static/js/modal.js`

- [ ] **Step 1: Invoquer `/impeccable`**, puis ajouter les renderers

Ajouter avant `openNodeModal` :

```javascript
function renderDiagnostic(d) {
  const f = document.createDocumentFragment();
  if (!d) { f.append(field("Diagnostic", "non déclenché à cette étape")); return f; }
  f.append(field("Attribution", d.attribution));
  f.append(field("Route prise", d.route_taken === "stop" ? "stop (unattributed)" : d.route_taken));
  if (d.reason) f.append(longField("Raison", d.reason));
  if (d.consignes) f.append(longField("Consignes de correction", d.consignes));
  return f;
}

function renderRosterGap(r, inp) {
  const f = document.createDocumentFragment();
  if (!r) { f.append(field("Roster gap", "—")); return f; }
  f.append(fieldLines("Tags manquants au roster", r.missing_tags.length ? r.missing_tags : ["—"]));
  f.append(field("Conséquence", "aucun agent ne couvre ces tags — branche terminée sans exécution"));
  if (inp) f.append(longField("Sous-tâche", inp.description));
  return f;
}

function renderTagger(inp) {
  const f = document.createDocumentFragment();
  const tags = Object.entries(inp.required_tags).map(([t, lvl]) => `${t} ≥ ${lvl}`);
  f.append(fieldLines("Tags posés sur la racine", tags.length ? tags : ["—"]));
  // caveat assumé (spec §4.6) : la trace ne distingue pas tags inférés vs épinglés
  f.append(field("Origine", "inférés ou épinglés (non distingués par la trace)"));
  return f;
}
```

- [ ] **Step 2: Étendre `renderDivider` (origine) et brancher le switch**

Dans `renderDivider`, après le guard `if (!d.divided)`, insérer en tête :

```javascript
  f.append(field("Origine de la division", d.origin === "diagnostic"
    ? "diagnostic D3 (task_spec)" : "récupération D1 (unassigned)"));
```

Dans le `switch (node.type)` d'`openNodeModal`, ajouter avant `default` :

```javascript
    case "diagnostic": body = renderDiagnostic(step.detail.diagnostic); break;
    case "roster_gap": body = renderRosterGap(step.detail.roster_gap, step.detail.input); break;
    case "tagger": body = renderTagger(step.detail.input); break;
```

NOTE evaluator pass-aware : rien à coder — le jalon `EVALUATOR v2` porte déjà `detail.evaluator`
construit depuis la ré-éval (spec v2), et le jalon `EVALUATOR` pass 0 porte la spec v1. Le modal
existant `renderEvaluator(e, step)` affiche la bonne passe selon le jalon courant. Vérifier
seulement que `Output évalué` reste correct (le `winner_agent_id` est porté par les deux jalons).

- [ ] **Step 3: Valider navigateur**

Cliquer chaque type de nœud sur une session : DIAG (attribution/route/raison/consignes),
TAGGER (tags + origine non affirmée), DIVIDER (origine + sous-tâches + tags), EVALUATOR aux deux
jalons (specs v1/v2 distinctes en scrubbant). Aucun crash console.

- [ ] **Step 4: Commit**

```bash
git add dashboard/static/js/modal.js
git commit -m "feat(demo-p1): modals DIAG, roster gap, tagger, origine divider"
```

---

### Task 16: `sessions.js` — TODO hiérarchique navigable, follow-mode, scrubber enrichi

**Files:**
- Modify: `dashboard/static/js/tabs/sessions.js`

- [ ] **Step 1: Invoquer `/impeccable`**, puis câbler la caméra

1. Imports :

```javascript
import { renderGraph, bboxOf } from "../graph.js";
import { attachCamera } from "../camera.js";
```

2. Markup : dans le template du panel, ajouter le bouton follow dans `.graph-frame` après le `<svg>` :

```html
        <button class="follow-btn on" title="Auto-centrage sur le jalon actif">⌖ suivre</button>
```

3. Après la récupération des éléments DOM :

```javascript
  const followBtn = panel.querySelector(".follow-btn");
  const camera = attachCamera(svg, { onManual: () => followBtn.classList.remove("on") });
  followBtn.addEventListener("click", () => {
    camera.setFollow(true);
    followBtn.classList.add("on");
    rerender();   // re-déclenche le focus sur le jalon courant
  });
```

4. Dans `rerender()`, remplacer l'appel `renderGraph(...)` par :

```javascript
    const info = renderGraph(svg, graph, activeStepIndex,
      (node, step) => openNodeModal(node, stepForNode(node, step), detail.agents),
      agentNames, { keepViewBox: true });
    camera.setContent(info.width, info.height);
    const cur = graph.steps[activeStepIndex];
    if (cur) camera.focusOn(bboxOf(cur.active_nodes, info.pos));
```

- [ ] **Step 2: TODO hiérarchique navigable**

Remplacer le corps de la boucle de `renderTodo()` (construction de `row`) pour porter
l'indentation par `depth`, la note de marge, et la navigation backend :

```javascript
    for (const t of items) {
      const row = document.createElement("div");
      row.className = `todo-item todo--${t.state}${t.is_root ? "" : " todo--sub"}`;
      row.style.marginLeft = `${t.depth * 14}px`;
      row.title = "Aller au premier jalon de cette tâche";

      const mk = document.createElement("span");
      mk.className = "mk";
      const text = document.createElement("span");
      text.className = "todo-text";
      text.textContent = t.description;
      row.append(mk, text);

      if (t.note) {
        const note = document.createElement("span");
        note.className = "todo-note";
        note.textContent = t.note;
        row.appendChild(note);
      }

      const exp = document.createElement("button");
      exp.className = "todo-expand";
      const label = t.is_root ? "Voir l'input complet" : "Voir la description complète";
      exp.title = label;
      exp.setAttribute("aria-label", label);
      exp.textContent = "⤢";
      exp.addEventListener("click", (ev) => {
        ev.stopPropagation();
        openTextModal((t.is_root ? "Input · " : "Sous-tâche · ") + t.id, t.description);
      });
      row.appendChild(exp);

      row.addEventListener("click", () => {
        if (t.first_step_index != null) { activeStepIndex = t.first_step_index; rerender(); }
      });
      todo.appendChild(row);
    }
```

Supprimer la fonction `firstStepIndexForTask` (le calcul vit côté backend désormais).

- [ ] **Step 3: `stepForNode` namespacé + label scrubber enrichi**

1. `stepForNode` — les divider/aggregator sont par niveau : matcher sur `node.task_id` :

```javascript
  function stepForNode(node, current) {
    if (node.type === "aggregator" || node.type === "divider") {
      if (current && current.active_nodes.includes(node.id)) return current;
      const mi = graph.steps.findIndex(s =>
        s.milestone_type === node.type && s.sub_task_id === node.task_id);
      if (mi >= 0 && activeStepIndex >= mi) return graph.steps[mi];
    }
    return current;
  }
```

2. Label scrubber : le label backend porte déjà `ROSTER GAP` / `DIAGNOSTIC · route X` /
`· pass 2` / `EVALUATOR v2`. Ajouter la sous-tâche concernée :

```javascript
      const sub = step.sub_task_id
        ? (step.todo.find(t => t.id === step.sub_task_id)?.description || "")
        : "";
      const subTxt = sub && !step.todo.find(t => t.id === step.sub_task_id)?.is_root
        ? ` <span class="scrub-sub">· ${esc(sub.slice(0, 48))}${sub.length > 48 ? "…" : ""}</span>` : "";
      scrubLabel.innerHTML = `Jalon <b>${activeStepIndex + 1}</b> / ${n} — <span class="mono">${esc(step.label)}</span>${subTxt}`;
```

(Ajouter `.scrub-sub { color: var(--fg-2); }` dans le CSS de la Task 14 si absent.)

3. `renderChips` : `graph.steps.find(s => s.milestone_type === "divider")` reste valide ;
le compte de sous-tâches devient `graph.tasks.length - 1` (toutes profondeurs) :

```javascript
    const subCount = Math.max(0, (graph.tasks || []).length - 1);
```

- [ ] **Step 4: Valider navigateur (flux complet)**

Dashboard, session divisée réelle : l'arbre pousse au scrub (les branches s'allument dans l'ordre
du run), follow-mode suit le jalon actif, molette/drag suspendent (`⌖ suivre` éteint), le bouton
réactive et recentre ; TODO indentée, items cliquables (saut au jalon), notes de marge ; labels
scrubber avec la sous-tâche.

- [ ] **Step 5: Commit**

```bash
git add dashboard/static/js/tabs/sessions.js dashboard/static/css
git commit -m "feat(demo-p1): sessions — caméra follow, TODO hiérarchique navigable, scrubber enrichi"
```

---

### Task 17: `/impeccable critique` + `polish`, validation end-to-end, DoD, CLAUDE.md

**Files:** validation + retouches éventuelles + `CLAUDE.md`

- [ ] **Step 1: Run réel + suite complète**

Run: `.venv\Scripts\python src\aaosa\demo\run_demo_v3.py` (requiert `OPENAI_API_KEY`) — produit
une session `run_recovery` persistée dans `runs/sessions/`.
Run: `.venv\Scripts\python -m pytest -q`
Expected: PASS complet.

- [ ] **Step 2: `/impeccable critique` sur le tab Sessions**

Invoquer `/impeccable critique` (cible : tab Sessions sur le run réel). Traiter les findings
bloquants (lisibilité de l'arbre, hiérarchie, densité, contrastes AA). C'est ICI que la réserve
de Quentin sur l'arbre pur se tranche : si la critique révèle une densité illisible de nœuds
dupliqués, présenter à Quentin le fallback spec §8 (tier d'agents global) AVANT de continuer.

- [ ] **Step 3: `/impeccable polish` sur le tab Sessions**

Invoquer `/impeccable polish` — passe finale : alignements de la grille k-rows, rythme des
chanfreins, états hover/focus du bouton ⌖ et des nœuds, cohérence mono/tracking des labels.

- [ ] **Step 4: Checklist navigateur Sessions (DoD spec §6.3)**

- [ ] arbre bottom-up : racines en bas, hauteur = profondeur de subdivision
- [ ] run divisé réel : division, arches par branche, descentes, replay jalon par jalon
- [ ] bus d'émission/collecte : rails + risers + points de jonction (croisement sans point = rien)
- [ ] colorway : montées crest, descentes ember, transients pointillés ; pulses directionnels
- [ ] follow-mode : auto-centrage, suspension par molette/drag, ⌖ réactive
- [ ] TODO : indentation, révélation au DIVIDER, navigation par clic, notes de marge
- [ ] modals : DIAG (attribution/route/consignes), ROSTER GAP (tags), EVALUATOR pass-aware (v1/v2),
      DIVIDER (origine + tags), TAGGER, AGENT, TOOL, AGGREGATOR
- [ ] labels scrubber : `ROSTER GAP`, `DIAGNOSTIC · route X`, `· pass 2`, `EVALUATOR v2`, sous-tâche
- [ ] run simple (session non divisée) : arbre dégénéré INPUT→TAGGER→DISPATCH→AGENT→EVAL→OUTPUT

Les chemins D3/roster_gap sans occurrence réelle : valider via une session synthétique — flusher
une trace de fixtures dans `runs/sessions/` avec un petit script jetable basé sur
`tests/dashboard/test_build_graph_tree.py::divided_fixture` + `Tracer.flush` + `save_session`
(le supprimer après validation).

- [ ] **Step 5: Non-régression tab Health**

Dashboard, tab Health : ouvrir un case-graph. Expected : arbre dégénéré single-task rendu en
`fullPath` (union), aucun crash, pas de caméra (le tab health n'attache pas `camera.js`).
NOTE : le nœud `testset` a disparu du graphe (décision d'implémentation 4 du plan) — confirmer
avec Quentin que le tab Health reste lisible sans lui.

- [ ] **Step 6: Sign-off Quentin (DoD 5)**

Présenter : le run réel rejoué, la checklist cochée, la décision arbre pur vs fallback §8,
la disparition du nœud testset. Attendre le sign-off explicite avant le commit final.

- [ ] **Step 7: CLAUDE.md + commit final**

Mettre à jour la section « État courant » de `CLAUDE.md` : nouvelle entrée « V3 — démo phase 1
observabilité série D » (events DiagnosedEvent + QA v2, build_graph arbre, frontend bottom-up,
N tests). Mettre à jour la ligne « Reste » si pertinent. Puis :

```bash
git add CLAUDE.md
git commit -m "docs(demo-p1): phase 1 observabilité série D — arbre émergent rendu end-to-end"
```

---

## Self-Review (couverture spec)

- **§3.1 `DiagnosedEvent` (seul event, émis y compris sur échec LLM, union)** → Tasks 1-2. ✓
- **§3.2 ré-éval visible (2e `QAEvaluatedEvent` runner, spec régénérée)** → Task 2. ✓
- **§3.3 zéro event retry — inférence passe + origine division** → Tasks 4, 8. ✓
- **§4.1 partition `task_id` + passes (`pass_index`)** → Task 4 (parsing), Task 8 (jalons). ✓
- **§4.2 arbre depuis TOUS les `TaskDividedEvent`, racine meta** → Task 4. ✓
- **§4.3 nœuds namespacés + globaux input/output/tagger + agent_id réels (×N frontend)** → Tasks 5, 12. ✓
- **§4.4 modèle : Outcome/NodeType/MilestoneType/GraphEdge.flow/GraphStep.pass_index/StepDetail.diagnostic+roster_gap/TodoItem hiérarchique (first_step_index backend)** → Task 3 (+ Task 10 pour la TODO). ✓
- **§4.5 walk unique, run simple = arbre dégénéré, contrat cassé assumé** → Tasks 6-7, 11. ✓
- **§4.6 honnêteté : aggregator sur event réel only, sinks only descendent, deps transient, roster_gap sans Phase1, diagnostic ≤1/tâche, tagger caveat pinned** → Tasks 5, 7, 9, 15 (caveat dans le modal). ✓
- **§5.1 layout bottom-up, arches, paires, DIAG losange warn, GAP fail terminal** → Tasks 12, 14. ✓
- **§5.2 delta 45°, point = jonction** → Task 12 (routage), Task 14 (styles). ✓
- **§5.3 crest→fire + pulses directionnels + amendement DESIGN.md + réserve --cool maintenue** → Task 14. ✓
- **§5.4 caméra zoom/pan/follow débrayable, auto-fit** → Tasks 13, 16. ✓
- **§5.5 TODO hiérarchique (indentation, annotations, clic = saut)** → Tasks 10 (backend), 16 (frontend). ✓
- **§5.6 modals DIAG/ROSTER GAP/evaluator pass-aware/DIVIDER tags+origine** → Task 15. ✓
- **§5.7 labels scrubber enrichis** → backend (labels Tasks 6-9) + Task 16. ✓
- **§6.1 TDD backend + fixtures synthétiques chemins rares** → Tasks 1-10. ✓
- **§6.2 frontend hors TDD auto, contrat live + checklist** → Tasks 12-17. ✓
- **§6.3 DoD 1-5** → Task 17 (suite verte, run réel, checklist, health, sign-off). ✓
- **§7 hors scope (live mode, multi-runs, phases 2-5, TaggedEvent)** → non touchés. ✓
- **§8 fallback tier global** → point de décision explicite Task 17 Step 2. ✓

## Limitations assumées (documentées)

- **Agrégation fallback** (`sinks[-1]` sur exception aggregator) : aucun event → rendue comme un
  court-circuit depuis le dernier sink. Déjà assumé vague 2/D2.
- **Deps inter-sœurs** : l'arête `transient` exit(dep)→dispatch(consommateur) est structurelle
  (idle wire) — pas de jalon dédié au transfert (le récit reste porté par l'ordre des branches).
- **Sous-tâche jamais tracée** (dep sautée par échec amont) : aucune branche rendue, item TODO
  `pending` à jamais — honnête : elle n'a jamais tourné.
- **GraphEdge.flow par défaut `"ascent"`** : choisi pour la compat des constructions de tests ;
  le builder pose toujours le flow explicitement.
- **Nœud `testset` retiré** (décision d'implémentation 4) — à confirmer au sign-off.
- **`agent_id` du `DiagnosedEvent`** : toujours renseigné depuis `QAFailure.agent_id` en pratique ;
  le champ reste nullable conformément à la spec (« None si inconnu »).

## Execution handoff

Exécution recommandée : **subagent-driven** (superpowers:subagent-driven-development), une task par
subagent, review entre les tasks. Branche : `feat/v3-demo-phase1-observabilite` (worktree isolé via
superpowers:using-git-worktrees). Les Tasks 12-17 (frontend) doivent être exécutées dans la session
principale (besoin du navigateur + `/impeccable`), pas en subagent.


