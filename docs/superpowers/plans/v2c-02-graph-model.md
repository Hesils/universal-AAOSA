# V2c — Épique 02 — Modèle de graphe (`build_graph`) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construire la fonction pure `build_graph(events, session_meta) -> GraphModel` qui transforme une trace d'events en un modèle de graphe 3 couches navigable, après avoir enrichi la couche data pour que les overlays disposent de toute l'information utile (output complet, breakdown QA + judge, required_tags).

**Architecture:** Deux phases. **Phase 0 (enrichissement data)** : 4 ajouts additifs/optionnels (rétrocompat préservée comme `llm_metadata` en Épique 01) répartis sur `tracing/`, `qa/`, `store.py`. **Phase 1 (build_graph)** : nouveau module pur `dashboard/graph_model.py`. Source de vérité = les **events** (winner/outcome dérivés des events). `session_meta` est optionnel et ne sert qu'à l'ordre et au label des steps. Une règle unique "garder le dernier run par `task_id`" couvre session (no-op) et health check (N runs → 1). L'enrichissement registry (system_prompt, ELO courant, nom d'agent) est **hors scope** : il est fait par la couche collector/API (Épique 03a).

**Tech Stack:** Python 3.14, Pydantic 2.13, pytest 9.0.3. Imports absolus uniquement. Timestamps UTC via `datetime.now(timezone.utc)`. `model_config = ConfigDict(extra="forbid")` sur tout modèle.

**Décisions de design (deep-dive 2026-05-29) :**
- **D1 — Events = source de vérité.** `winner_agent_id` = `DispatchedEvent.agent_id` (sinon `None`). `outcome` dérivé des events : `unassigned` (UnassignedEvent ou pas de dispatch) / `no_qa` (dispatch sans QAEvaluatedEvent) / `qa_pass` / `qa_fail`. `session_meta` ne fait pas autorité sur winner/outcome.
- **D2 — Règle "dernier run par task_id" universelle.** Les runs d'un même `task_id` se segmentent sur le redémarrage d'un bloc `phase1_filtered`. On ne garde que le dernier run. No-op en session (1 run/task), correct en health check (N runs → le dernier).
- **D3 — `build_graph` est pur sur (events, meta).** Il n'a pas accès au registry. Le détail Agent n'expose que le dérivable des events (fit_score, claim, output, ELO deltas). L'enrichissement `system_prompt` / ELO courant / nom est ajouté par l'API en Épique 03a. Le `label` d'un nœud agent = son `agent_id` ; le frontend résout le nom via `/api/agents`.
- **D4 — `pass_rate` + sélection de cas health check = job du collector (Épique 03a).** `build_graph` est agnostique au mode : le collector pré-filtre la trace au cas voulu puis appelle `build_graph`. `build_graph` ne connaît pas le `pass_rate`.
- **Topologie fixe** : 5 nœuds toujours présents (input/dispatch/evaluator/output/testset) + 1 nœud par agent vu. Layout stable ; les nœuds inactifs sont grisés par step. Aucun nœud V3.
- **Enrichissements (E1-E4)** confirmés, dont E3 qui touche le contrat V2b `QAResult` (additif/optionnel, `rule_based` inchangé).

---

## Store / contrat cible après Phase 0

```
ExecutedEvent       += output_content: str | None = None
QAResult            += judge: JudgeBreakdown | None = None        # contrat V2b (additif)
QAEvaluatedEvent    += criteria_results: dict[str, bool] = {}
                    += judge: JudgeBreakdown | None = None
SessionTaskRecord   += required_tags: dict[str, int]              # requis (run_demo le remplit)
JudgeBreakdown(mode, overall, dimension_scores, reason)           # nouveau, dans qa/judge.py
```

## GraphModel cible (Phase 1)

```
GraphModel  { nodes: [GraphNode], edges: [GraphEdge], steps: [GraphStep] }
GraphNode   { id, layer: top|center|bottom, type: input|dispatch|evaluator|output|testset|agent, label }
GraphEdge   { from, to }                       # field interne from_node, alias JSON "from"
GraphStep   { task_id, label, active_nodes: [str], active_edges: [GraphEdge],
              winner_agent_id: str|None, outcome, detail: StepDetail }
StepDetail  { input: InputDetail, dispatch: DispatchDetail, agents: {agent_id: AgentDetail},
              evaluator: EvaluatorDetail, output: OutputDetail, testset: TestSetDetail }
```

## File Structure

| Fichier | Responsabilité | Action |
|---|---|---|
| `src/aaosa/tracing/events.py` | `ExecutedEvent.output_content` ; `QAEvaluatedEvent.criteria_results` + `.judge` | Modifier |
| `src/aaosa/qa/judge.py` | nouveau `JudgeBreakdown` | Modifier |
| `src/aaosa/qa/protocol.py` | `QAResult.judge: JudgeBreakdown \| None = None` | Modifier |
| `src/aaosa/qa/spec_evaluator.py` | peupler `judge` quand le judge tourne | Modifier |
| `src/aaosa/runtime/runner.py` | câbler `output_content`, `criteria_results`, `judge` dans les events | Modifier |
| `src/aaosa/qa/health_check.py` | câbler `criteria_results`, `judge` dans `QAEvaluatedEvent` | Modifier |
| `src/aaosa/tracing/store.py` | `SessionTaskRecord.required_tags` | Modifier |
| `src/aaosa/demo/run_demo.py` | passer `required_tags=task.required_tags` | Modifier |
| `dashboard/__init__.py` | rendre `dashboard` importable | Créer |
| `dashboard/graph_model.py` | modèles + helpers + `build_graph` (fonction pure) | Créer |
| `conftest.py` (racine repo) | mettre la racine repo sur `sys.path` (import `dashboard`) | Créer |
| `tests/tracing/test_events_v2.py` | tests des nouveaux champs d'events | Modifier |
| `tests/qa/test_spec_evaluator.py` | test `QAResult.judge` peuplé | Modifier |
| `tests/runtime/test_runner.py` | assertions câblage runner | Modifier |
| `tests/qa/test_health_check.py` | assertions câblage health check | Modifier |
| `tests/tracing/test_store.py` | `required_tags` + maj `make_meta` existant | Modifier |
| `tests/dashboard/test_graph_model.py` | tests de `build_graph` (6 scénarios) | Créer |

---

# PHASE 0 — Enrichissement de la couche data

## Task 1: `ExecutedEvent.output_content` + câblage runner

**Files:**
- Modify: `src/aaosa/tracing/events.py:36-40` (`ExecutedEvent`)
- Modify: `src/aaosa/runtime/runner.py:37-43` (émission `ExecutedEvent`)
- Test: `tests/tracing/test_events_v2.py`, `tests/runtime/test_runner.py`

- [ ] **Step 1: Écrire les tests `output_content` (events)**

Ajouter à la fin de `tests/tracing/test_events_v2.py` :

```python
class TestExecutedEventOutputContent:
    def test_defaults_to_none(self):
        """Rétrocompat : output_content optionnel, défaut None."""
        e = ExecutedEvent(
            session_id="s1", task_id="t1",
            agent_id="a1", output_summary="done",
        )
        assert e.output_content is None

    def test_carries_full_content(self):
        e = ExecutedEvent(
            session_id="s1", task_id="t1",
            agent_id="a1", output_summary="done"[:100],
            output_content="the full multi-line output content",
        )
        assert e.output_content == "the full multi-line output content"

    def test_json_roundtrip_with_content(self):
        e = ExecutedEvent(
            session_id="s1", task_id="t1",
            agent_id="a1", output_summary="done",
            output_content="full body",
        )
        e2 = ExecutedEvent.model_validate_json(e.model_dump_json())
        assert e2.output_content == "full body"
```

> `ExecutedEvent` est déjà importé en haut de ce fichier (tests `llm_metadata` de l'Épique 01). Si l'import manque, ajouter `from aaosa.tracing.events import ExecutedEvent`.

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/tracing/test_events_v2.py::TestExecutedEventOutputContent -v`
Expected: FAIL — `ExecutedEvent() got an unexpected keyword argument 'output_content'` (extra=forbid).

- [ ] **Step 3: Ajouter le champ optionnel**

Dans `src/aaosa/tracing/events.py`, modifier `ExecutedEvent` :

```python
class ExecutedEvent(_BaseEvent):
    type: Literal["executed"] = "executed"
    agent_id: str
    output_summary: str
    output_content: str | None = None
    llm_metadata: LLMMetadata | None = None
```

- [ ] **Step 4: Lancer les tests events, vérifier le succès**

Run: `.venv\Scripts\python -m pytest tests/tracing/test_events_v2.py -v`
Expected: PASS (nouveaux + anciens).

- [ ] **Step 5: Écrire le test de propagation runner**

Ajouter à `tests/runtime/test_runner.py` (après `test_run_task_executed_event_carries_llm_metadata`) :

```python
def test_run_task_executed_event_carries_output_content():
    """L'ExecutedEvent émis porte le contenu complet de l'Output."""
    task = make_task()
    agent = make_agent("AgentA", 80)
    claim = make_claim(agent, task, "claim")
    output = make_output(agent, task)
    tracer = Tracer(session_id="s1")

    with patch.object(Agent, "claim", return_value=claim):
        with patch.object(Agent, "execute", return_value=output):
            run_task(task, [agent], MagicMock(), tracer=tracer)

    executed = [e for e in tracer.events if isinstance(e, ExecutedEvent)]
    assert len(executed) == 1
    assert executed[0].output_content == output.content
    assert executed[0].output_summary == output.content[:100]
```

- [ ] **Step 6: Lancer le test, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_runner.py::test_run_task_executed_event_carries_output_content -v`
Expected: FAIL — `assert None == '...'` (runner ne passe pas encore `output_content`).

- [ ] **Step 7: Câbler le runner**

Dans `src/aaosa/runtime/runner.py`, modifier l'émission de l'`ExecutedEvent` (lignes 37-43) :

```python
    if tracer is not None:
        tracer.emit(ExecutedEvent(
            session_id=tracer.session_id,
            task_id=task.id,
            agent_id=winner.id,
            output_summary=output.content[:100],
            output_content=output.content,
            llm_metadata=output.llm_metadata,
        ))
```

- [ ] **Step 8: Lancer les tests runner**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_runner.py -v`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/aaosa/tracing/events.py src/aaosa/runtime/runner.py tests/tracing/test_events_v2.py tests/runtime/test_runner.py
git commit -m "feat(v2c): ExecutedEvent.output_content + wiring runner"
```

---

## Task 2: `JudgeBreakdown` + `QAResult.judge` (contrat V2b, additif)

**Files:**
- Modify: `src/aaosa/qa/judge.py` (nouveau `JudgeBreakdown`)
- Modify: `src/aaosa/qa/protocol.py` (`QAResult.judge`)
- Modify: `src/aaosa/qa/spec_evaluator.py` (peupler `judge`)
- Test: `tests/qa/test_spec_evaluator.py`

> **Rappel cycle d'import** : `protocol.py` importe `judge.py` ; `judge.py` importe `qa.spec` (qui n'importe rien de `qa`). Acyclique. `rule_based.py` construit `QAResult` sans `judge` → reste valide grâce au défaut `None`, aucune modification.

- [ ] **Step 1: Écrire le test `QAResult.judge` peuplé**

Ouvrir `tests/qa/test_spec_evaluator.py` et repérer comment les tests existants stubent le client OpenAI pour le judge (réutiliser le même pattern de mock). Ajouter ce test, en adaptant la construction du mock client à celle déjà présente dans le fichier (le judge appelle `client.beta.chat.completions.parse(...)` et lit `.choices[0].message.parsed`, qui doit être un `JudgeResult`) :

```python
from aaosa.qa.judge import JudgeBreakdown, JudgeResult, DimensionScore


class TestQAResultJudgeBreakdown:
    def test_judge_breakdown_populated_when_judge_runs(self):
        spec = EvaluatorSpec(
            criteria=[CriterionSpec(name="non_empty", gate=True)],
            judge=JudgeSpec(rubric=["clarity"], weight=0.3, mode="rubric"),
            success_threshold=0.5,
        )
        judge_result = JudgeResult(
            dimension_scores=[DimensionScore(name="clarity", score=0.8)],
            overall=0.8, reason="clear",
        )
        client = _mock_client_returning(judge_result)  # helper local du fichier de test
        evaluator = from_spec(spec, client=client)

        task = Task(description="t", required_tags={"python": 50})
        output = Output(
            agent_id="a1", task_id=task.id,
            content="a sufficiently long answer about python " * 3,
        )
        result = evaluator.evaluate(task, output)

        assert result.judge is not None
        assert result.judge.mode == "rubric"
        assert result.judge.overall == 0.8
        assert result.judge.reason == "clear"
        assert result.judge.dimension_scores[0].name == "clarity"

    def test_judge_none_when_no_judge(self):
        spec = EvaluatorSpec(criteria=[CriterionSpec(name="non_empty", gate=True)])
        evaluator = from_spec(spec)
        task = Task(description="t", required_tags={"python": 50})
        output = Output(agent_id="a1", task_id=task.id, content="non empty")
        result = evaluator.evaluate(task, output)
        assert result.judge is None
```

> Si `_mock_client_returning` n'existe pas dans le fichier, factoriser le mock du judge déjà utilisé par les tests existants en une petite fonction locale, ou inliner le `MagicMock` configuré pour renvoyer `judge_result` via `client.beta.chat.completions.parse(...).choices[0].message.parsed`. Vérifier les imports `Output`, `Task`, `EvaluatorSpec`, `CriterionSpec`, `JudgeSpec`, `from_spec` (réutiliser ceux du fichier).

- [ ] **Step 2: Lancer le test, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/qa/test_spec_evaluator.py::TestQAResultJudgeBreakdown -v`
Expected: FAIL — `ImportError: cannot import name 'JudgeBreakdown'` (puis, une fois l'import résolu, `AttributeError`/`extra=forbid` sur `result.judge`).

- [ ] **Step 3: Ajouter `JudgeBreakdown` dans `judge.py`**

Dans `src/aaosa/qa/judge.py`, ajouter `Literal` à l'import typing en haut du fichier :

```python
from typing import Literal
```

Puis, après la définition de `JudgeResult` (autour de la ligne 19), ajouter :

```python
class JudgeBreakdown(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["rubric", "reference_based"]
    overall: float
    dimension_scores: list[DimensionScore]
    reason: str
```

- [ ] **Step 4: Ajouter le champ `judge` à `QAResult`**

Dans `src/aaosa/qa/protocol.py`, ajouter l'import après les imports existants :

```python
from aaosa.qa.judge import JudgeBreakdown
```

Puis modifier `QAResult` (ajouter le champ en dernier) :

```python
class QAResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    agent_id: str
    success: bool
    score: float          # 0.0-1.0
    reason: str
    criteria_results: dict[str, bool]
    judge: JudgeBreakdown | None = None
```

- [ ] **Step 5: Peupler `judge` dans `SpecEvaluator`**

Dans `src/aaosa/qa/spec_evaluator.py`, modifier l'import du judge :

```python
from aaosa.qa.judge import JudgeBreakdown, run_judge
```

Puis remplacer le bloc "3. Judge" et "4. Verdict" (lignes 54-71) par :

```python
        # 3. Judge
        reason = "deterministic criteria evaluated"
        judge_breakdown: JudgeBreakdown | None = None
        if self.spec.judge is not None:
            judge_result = run_judge(
                task, output, self.spec.judge, self.client, self.reference
            )
            w = self.spec.judge.weight
            final = (1.0 - w) * det_score + w * judge_result.overall
            reason = f"det={det_score:.2f} judge={judge_result.overall:.2f} ({judge_result.reason})"
            judge_breakdown = JudgeBreakdown(
                mode=self.spec.judge.mode,
                overall=judge_result.overall,
                dimension_scores=judge_result.dimension_scores,
                reason=judge_result.reason,
            )
        else:
            final = det_score

        # 4. Verdict
        return QAResult(
            task_id=task.id, agent_id=output.agent_id,
            success=final >= self.spec.success_threshold,
            score=final, reason=reason, criteria_results=criteria_results,
            judge=judge_breakdown,
        )
```

> Le retour anticipé "gate failed" (lignes 33-39) construit un `QAResult` sans `judge` → reste `None` par défaut. Ne pas le modifier.

- [ ] **Step 6: Lancer la suite QA, vérifier le succès + non-régression**

Run: `.venv\Scripts\python -m pytest tests/qa/ -v`
Expected: PASS (nouveaux tests + toute la suite QA V2b inchangée).

- [ ] **Step 7: Commit**

```bash
git add src/aaosa/qa/judge.py src/aaosa/qa/protocol.py src/aaosa/qa/spec_evaluator.py tests/qa/test_spec_evaluator.py
git commit -m "feat(v2c): JudgeBreakdown + QAResult.judge (additif, retrocompat)"
```

---

## Task 3: `QAEvaluatedEvent.criteria_results` + `.judge` + câblage

**Files:**
- Modify: `src/aaosa/tracing/events.py:48-53` (`QAEvaluatedEvent`)
- Modify: `src/aaosa/runtime/runner.py:50-58` (émission QA)
- Modify: `src/aaosa/qa/health_check.py:70-75` (émission QA)
- Test: `tests/tracing/test_events_v2.py`, `tests/runtime/test_runner.py`, `tests/qa/test_health_check.py`

- [ ] **Step 1: Écrire les tests `QAEvaluatedEvent` (events)**

Ajouter à la fin de `tests/tracing/test_events_v2.py` :

```python
from aaosa.qa.judge import JudgeBreakdown, DimensionScore
from aaosa.tracing.events import QAEvaluatedEvent


class TestQAEvaluatedEventEnrichment:
    def test_criteria_results_defaults_empty(self):
        e = QAEvaluatedEvent(
            session_id="s1", task_id="t1", agent_id="a1",
            success=True, score=1.0, reason="ok",
        )
        assert e.criteria_results == {}
        assert e.judge is None

    def test_carries_criteria_and_judge(self):
        jb = JudgeBreakdown(
            mode="rubric", overall=0.8,
            dimension_scores=[DimensionScore(name="clarity", score=0.8)],
            reason="clear",
        )
        e = QAEvaluatedEvent(
            session_id="s1", task_id="t1", agent_id="a1",
            success=True, score=0.9, reason="ok",
            criteria_results={"non_empty": True, "min_length": True},
            judge=jb,
        )
        assert e.criteria_results["non_empty"] is True
        assert e.judge is not None
        assert e.judge.mode == "rubric"

    def test_json_roundtrip(self):
        jb = JudgeBreakdown(
            mode="reference_based", overall=0.5,
            dimension_scores=[], reason="meh",
        )
        e = QAEvaluatedEvent(
            session_id="s1", task_id="t1", agent_id="a1",
            success=False, score=0.5, reason="x",
            criteria_results={"gate": False}, judge=jb,
        )
        e2 = QAEvaluatedEvent.model_validate_json(e.model_dump_json())
        assert e2.criteria_results == {"gate": False}
        assert e2.judge.mode == "reference_based"
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/tracing/test_events_v2.py::TestQAEvaluatedEventEnrichment -v`
Expected: FAIL — `got an unexpected keyword argument 'criteria_results'`.

- [ ] **Step 3: Enrichir `QAEvaluatedEvent`**

Dans `src/aaosa/tracing/events.py`, ajouter l'import du `JudgeBreakdown` après l'import `LLMMetadata` :

```python
from aaosa.qa.judge import JudgeBreakdown
```

> Vérifier l'absence de cycle : `events.py` importe déjà `aaosa.schemas.output`. `aaosa.qa.judge` importe `qa.spec` + `schemas.output` + `schemas.task` ; aucun n'importe `tracing.events`. Acyclique.

Puis modifier `QAEvaluatedEvent` :

```python
class QAEvaluatedEvent(_BaseEvent):
    type: Literal["qa_evaluated"] = "qa_evaluated"
    agent_id: str
    success: bool
    score: float
    reason: str
    criteria_results: dict[str, bool] = Field(default_factory=dict)
    judge: JudgeBreakdown | None = None
```

> `Field` est déjà importé en haut de `events.py`.

- [ ] **Step 4: Lancer les tests events**

Run: `.venv\Scripts\python -m pytest tests/tracing/test_events_v2.py -v`
Expected: PASS.

- [ ] **Step 5: Écrire le test de câblage runner**

Ajouter à `tests/runtime/test_runner.py`. Ce test exige un evaluator qui renvoie un `QAResult` avec `criteria_results` et `judge` peuplés ; construire un faux evaluator local plutôt que d'appeler un vrai LLM :

```python
def test_run_task_qa_event_carries_criteria_and_judge():
    """L'event QA émis porte criteria_results et judge du QAResult."""
    from aaosa.qa.judge import JudgeBreakdown, DimensionScore
    from aaosa.qa.protocol import QAResult
    from aaosa.tracing.events import QAEvaluatedEvent

    task = make_task()
    agent = make_agent("AgentA", 80)
    claim = make_claim(agent, task, "claim")
    output = make_output(agent, task)
    tracer = Tracer(session_id="s1")

    qa = QAResult(
        task_id=task.id, agent_id=agent.id, success=True, score=0.9,
        reason="ok", criteria_results={"non_empty": True},
        judge=JudgeBreakdown(
            mode="rubric", overall=0.9,
            dimension_scores=[DimensionScore(name="clarity", score=0.9)],
            reason="clear",
        ),
    )

    class _FakeEvaluator:
        def evaluate(self, t, o):
            return qa

    with patch.object(Agent, "claim", return_value=claim):
        with patch.object(Agent, "execute", return_value=output):
            run_task(task, [agent], MagicMock(), tracer=tracer, evaluator=_FakeEvaluator())

    qa_events = [e for e in tracer.events if isinstance(e, QAEvaluatedEvent)]
    assert len(qa_events) == 1
    assert qa_events[0].criteria_results == {"non_empty": True}
    assert qa_events[0].judge is not None
    assert qa_events[0].judge.overall == 0.9
```

- [ ] **Step 6: Lancer le test, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_runner.py::test_run_task_qa_event_carries_criteria_and_judge -v`
Expected: FAIL — `criteria_results == {}` et `judge is None` (runner ne câble pas encore).

- [ ] **Step 7: Câbler le runner (émission QA)**

Dans `src/aaosa/runtime/runner.py`, modifier l'émission du `QAEvaluatedEvent` (lignes 50-58) :

```python
    if tracer is not None:
        tracer.emit(QAEvaluatedEvent(
            session_id=tracer.session_id,
            task_id=task.id,
            agent_id=winner.id,
            success=qa_result.success,
            score=qa_result.score,
            reason=qa_result.reason,
            criteria_results=qa_result.criteria_results,
            judge=qa_result.judge,
        ))
```

- [ ] **Step 8: Câbler le health check (émission QA)**

Dans `src/aaosa/qa/health_check.py`, modifier l'émission du `QAEvaluatedEvent` (lignes 70-75) :

```python
            if tracer is not None:
                tracer.emit(QAEvaluatedEvent(
                    session_id=tracer.session_id, task_id=case.task.id,
                    agent_id=result.agent_id, success=qa.success,
                    score=qa.score, reason=qa.reason,
                    criteria_results=qa.criteria_results, judge=qa.judge,
                ))
```

- [ ] **Step 9: Ajouter un test de câblage health check**

Ouvrir `tests/qa/test_health_check.py`. Repérer un test existant qui exécute `run_health_check` avec un `tracer` et un client mocké renvoyant un `Output` (réutiliser ses fixtures/mocks). Ajouter une assertion sur l'event QA émis, dans un nouveau test calqué sur ce pattern :

```python
def test_health_check_qa_event_carries_criteria_results(<fixtures du fichier>):
    # ... construire test_set + agents + client mock comme les tests existants ...
    tracer = Tracer(session_id="hc-x")
    run_health_check(agents, test_set, client, n_runs=1, tracer=tracer)
    qa_events = [e for e in tracer.events if isinstance(e, QAEvaluatedEvent)]
    assert qa_events  # au moins un
    assert isinstance(qa_events[0].criteria_results, dict)
```

> Adapter les fixtures aux helpers déjà présents dans `test_health_check.py`. Si le fichier mocke `run_task` plutôt qu'un vrai LLM, s'assurer que le mock renvoie un `Output` afin que la branche d'émission QA soit atteinte. `QAEvaluatedEvent` est déjà importé dans ce fichier (Épique 01).

- [ ] **Step 10: Lancer les suites concernées**

Run: `.venv\Scripts\python -m pytest tests/runtime/test_runner.py tests/qa/test_health_check.py -v`
Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add src/aaosa/tracing/events.py src/aaosa/runtime/runner.py src/aaosa/qa/health_check.py tests/tracing/test_events_v2.py tests/runtime/test_runner.py tests/qa/test_health_check.py
git commit -m "feat(v2c): QAEvaluatedEvent porte criteria_results + judge"
```

---

## Task 4: `SessionTaskRecord.required_tags` + câblage demo

**Files:**
- Modify: `src/aaosa/tracing/store.py:50-55` (`SessionTaskRecord`)
- Modify: `src/aaosa/demo/run_demo.py:56-59` (construction du record)
- Test: `tests/tracing/test_store.py`

- [ ] **Step 1: Mettre à jour le helper `make_meta` existant + ajouter un test**

Dans `tests/tracing/test_store.py`, le helper `make_meta` construit des `SessionTaskRecord` sans `required_tags`. Comme le champ devient **requis**, mettre à jour `make_meta` pour le fournir :

```python
        tasks=[
            SessionTaskRecord(
                id="t1", description="do a thing",
                winner_agent_id="a1", outcome="qa_pass",
                required_tags={"python": 50},
            ),
            SessionTaskRecord(
                id="t2", description="impossible",
                winner_agent_id=None, outcome="unassigned",
                required_tags={"rust": 90},
            ),
        ],
```

Puis ajouter un test dédié dans la classe `TestSessionTaskRecord` :

```python
    def test_required_tags_stored(self):
        rec = SessionTaskRecord(
            id="t1", description="x", winner_agent_id="a1",
            outcome="qa_pass", required_tags={"python": 50, "sql": 30},
        )
        assert rec.required_tags == {"python": 50, "sql": 30}

    def test_required_tags_is_required(self):
        import pytest
        with pytest.raises(Exception):
            SessionTaskRecord(
                id="t1", description="x", winner_agent_id="a1", outcome="qa_pass",
            )
```

Et renforcer `test_meta_roundtrip` (classe `TestSaveSession`) en ajoutant après les assertions existantes :

```python
        assert loaded.tasks[0].required_tags == {"python": 50}
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/tracing/test_store.py -v`
Expected: FAIL — `test_required_tags_is_required` échoue (champ encore optionnel/absent) et/ou `got an unexpected keyword argument 'required_tags'`.

- [ ] **Step 3: Ajouter le champ requis**

Dans `src/aaosa/tracing/store.py`, modifier `SessionTaskRecord` :

```python
class SessionTaskRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    description: str
    winner_agent_id: str | None
    outcome: TaskOutcome
    required_tags: dict[str, int]
```

- [ ] **Step 4: Lancer les tests store**

Run: `.venv\Scripts\python -m pytest tests/tracing/test_store.py -v`
Expected: PASS.

- [ ] **Step 5: Câbler `run_demo.py`**

Dans `src/aaosa/demo/run_demo.py`, modifier la construction du record (lignes 56-59) :

```python
        task_records.append(SessionTaskRecord(
            id=task.id, description=task.description,
            winner_agent_id=winner_id, outcome=outcome,
            required_tags=task.required_tags,
        ))
```

- [ ] **Step 6: Lancer les tests demo (non-régression)**

Run: `.venv\Scripts\python -m pytest tests/demo/test_demo.py -v`
Expected: PASS (les tests monkeypatchent `save_session`, donc la construction du record est exercée sans I/O réel).

- [ ] **Step 7: Commit**

```bash
git add src/aaosa/tracing/store.py src/aaosa/demo/run_demo.py tests/tracing/test_store.py
git commit -m "feat(v2c): SessionTaskRecord.required_tags + wiring run_demo"
```

---

# PHASE 1 — `build_graph` (fonction pure)

## Task 5: Scaffolding `dashboard/` + modèles du graphe

**Files:**
- Create: `conftest.py` (racine repo)
- Create: `dashboard/__init__.py`
- Create: `dashboard/graph_model.py` (modèles uniquement)
- Test: `tests/dashboard/test_graph_model.py`

- [ ] **Step 1: Créer le `conftest.py` racine (import `dashboard`)**

`testpaths = ["tests"]` et `dashboard/` n'est pas un package installé. Créer `conftest.py` à la racine du repo pour mettre la racine sur `sys.path` :

```python
import sys
from pathlib import Path

ROOT = Path(__file__).parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
```

- [ ] **Step 2: Créer `dashboard/__init__.py`**

Fichier vide :

```python
```

- [ ] **Step 3: Écrire le test de construction des modèles**

Créer `tests/dashboard/test_graph_model.py` :

```python
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
```

- [ ] **Step 4: Lancer le test, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_graph_model.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dashboard.graph_model'`.

- [ ] **Step 5: Créer `dashboard/graph_model.py` (modèles)**

```python
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from aaosa.qa.judge import JudgeBreakdown
from aaosa.schemas.output import LLMMetadata
from aaosa.tracing.events import ClaimEvent
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
```

- [ ] **Step 6: Lancer le test, vérifier le succès**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_graph_model.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add conftest.py dashboard/__init__.py dashboard/graph_model.py tests/dashboard/test_graph_model.py
git commit -m "feat(v2c): graph_model - scaffolding dashboard + modeles GraphModel"
```

---

## Task 6: Segmentation des runs (`_segment_runs`)

**Files:**
- Modify: `dashboard/graph_model.py` (ajouter helpers + imports d'events concrets)
- Test: `tests/dashboard/test_graph_model.py`

- [ ] **Step 1: Écrire les tests de segmentation**

Ajouter en haut de `tests/dashboard/test_graph_model.py` les helpers de construction d'events et les imports :

```python
from aaosa.tracing.events import (
    DispatchedEvent,
    EloUpdatedEvent,
    ExecutedEvent,
    Phase1FilteredEvent,
    Phase2ClaimedEvent,
    QAEvaluatedEvent,
    TagAcquiredEvent,
    UnassignedEvent,
)
from dashboard.graph_model import _segment_runs, build_graph

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


def qa(tid, aid, success=True, score=1.0, reason="ok", criteria=None, judge=None):
    return QAEvaluatedEvent(session_id=SID, task_id=tid, agent_id=aid, success=success, score=score, reason=reason, criteria_results=criteria or {}, judge=judge)


def elo(tid, aid, deltas):
    return EloUpdatedEvent(session_id=SID, task_id=tid, agent_id=aid, deltas=deltas)


def tag(tid, aid, t, initial):
    return TagAcquiredEvent(session_id=SID, task_id=tid, agent_id=aid, tag=t, initial_elo=initial)
```

Puis ajouter la classe de test :

```python
class TestSegmentRuns:
    def test_single_run_returns_all(self):
        run = [p1("t1", "a"), p2("t1", "a"), disp("t1", "a"), ex("t1", "a"), qa("t1", "a")]
        assert _segment_runs(run) == run

    def test_session_run_keeps_trailing_elo(self):
        run = [p1("t1", "a"), disp("t1", "a"), ex("t1", "a"), qa("t1", "a"),
               elo("t1", "a", {"python": 5}), tag("t1", "a", "css", 50)]
        assert _segment_runs(run) == run

    def test_two_runs_keeps_last(self):
        run1 = [p1("t1", "a"), p1("t1", "b"), disp("t1", "a"), ex("t1", "a"), qa("t1", "a", success=False)]
        run2 = [p1("t1", "a"), p1("t1", "b"), disp("t1", "b"), ex("t1", "b"), qa("t1", "b", success=True)]
        last = _segment_runs(run1 + run2)
        assert last == run2

    def test_three_runs_keeps_last(self):
        def mk(winner):
            return [p1("t1", "a"), p1("t1", "b"), disp("t1", winner), ex("t1", winner), qa("t1", winner)]
        runs = mk("a") + mk("b") + mk("a")
        last = _segment_runs(runs)
        assert last == mk("a")

    def test_unassigned_run_segments(self):
        run1 = [p1("t1", "a"), unassigned("t1")]
        run2 = [p1("t1", "a"), disp("t1", "a"), ex("t1", "a"), qa("t1", "a")]
        assert _segment_runs(run1 + run2) == run2
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_graph_model.py::TestSegmentRuns -v`
Expected: FAIL — `ImportError: cannot import name '_segment_runs'`.

- [ ] **Step 3: Implémenter `_segment_runs` + imports d'events concrets**

Dans `dashboard/graph_model.py`, ajouter aux imports les classes d'events concrètes (pour les `isinstance`) :

```python
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
```

> Remplacer la ligne d'import `from aaosa.tracing.events import ClaimEvent` du Task 5 par ce bloc.

Puis ajouter, après les modèles, la fonction :

```python
def _segment_runs(task_events: list[ClaimEvent]) -> list[ClaimEvent]:
    """Découpe les events d'un même task_id en runs et renvoie le dernier.

    Un nouveau run démarre à un Phase1FilteredEvent dont le prédécesseur
    n'est pas un Phase1FilteredEvent. No-op en session (1 run), garde le
    dernier des N runs en health check.
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
```

- [ ] **Step 4: Lancer les tests segmentation**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_graph_model.py::TestSegmentRuns -v`
Expected: PASS.

> `build_graph` est importé par le fichier de test mais pas encore défini : les tests de segmentation passent car ils n'appellent pas `build_graph`. L'import échouera tant que `build_graph` n'existe pas. Pour cette raison, ajouter un stub minimal en fin de `dashboard/graph_model.py` afin que l'import résolve :
>
> ```python
> def build_graph(events: list[ClaimEvent], session_meta: SessionMeta | None = None) -> GraphModel:
>     raise NotImplementedError
> ```
>
> Il sera remplacé au Task 7.

- [ ] **Step 5: Commit**

```bash
git add dashboard/graph_model.py tests/dashboard/test_graph_model.py
git commit -m "feat(v2c): graph_model - _segment_runs (dernier run par task_id)"
```

---

## Task 7: `build_graph` — nœuds + arêtes (topologie statique)

**Files:**
- Modify: `dashboard/graph_model.py` (`_build_nodes`, `_build_edges`, `build_graph`)
- Test: `tests/dashboard/test_graph_model.py`

- [ ] **Step 1: Écrire les tests nœuds/arêtes**

Ajouter à `tests/dashboard/test_graph_model.py` :

```python
def _single_pass_run(tid="t1", winner="a", others=("b",)):
    events = [p1(tid, winner, True, 0.9)]
    for o in others:
        events.append(p1(tid, o, True, 0.4))
    events.append(p2(tid, winner, "claim", "mine"))
    events += [disp(tid, winner), ex(tid, winner), qa(tid, winner, success=True),
               elo(tid, winner, {"python": 5})]
    return events


class TestBuildNodesEdges:
    def test_fixed_nodes_present(self):
        model = build_graph(_single_pass_run())
        by_id = {n.id: n for n in model.nodes}
        assert by_id["input"].layer == "top"
        assert by_id["dispatch"].layer == "center"
        assert by_id["evaluator"].layer == "center"
        assert by_id["output"].layer == "top"
        assert by_id["testset"].layer == "top"

    def test_agent_nodes_bottom(self):
        model = build_graph(_single_pass_run(winner="a", others=("b",)))
        agents = [n for n in model.nodes if n.type == "agent"]
        assert {n.id for n in agents} == {"a", "b"}
        assert all(n.layer == "bottom" for n in agents)
        assert all(n.label == n.id for n in agents)  # label = agent_id (D3)

    def test_static_edges(self):
        model = build_graph(_single_pass_run(winner="a", others=("b",)))
        pairs = {(e.from_node, e.to) for e in model.edges}
        assert ("input", "dispatch") in pairs
        assert ("dispatch", "a") in pairs and ("dispatch", "b") in pairs
        assert ("a", "evaluator") in pairs and ("b", "evaluator") in pairs
        assert ("a", "output") in pairs and ("b", "output") in pairs
        assert ("evaluator", "output") in pairs
        assert ("evaluator", "testset") in pairs
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_graph_model.py::TestBuildNodesEdges -v`
Expected: FAIL — `NotImplementedError`.

- [ ] **Step 3: Implémenter `_build_nodes`, `_build_edges` et le squelette de `build_graph`**

Dans `dashboard/graph_model.py`, remplacer le stub `build_graph` par :

```python
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


def build_graph(events: list[ClaimEvent], session_meta: SessionMeta | None = None) -> GraphModel:
    nodes = _build_nodes(events)
    edges = _build_edges(nodes)
    return GraphModel(nodes=nodes, edges=edges, steps=[])
```

- [ ] **Step 4: Lancer les tests nœuds/arêtes**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_graph_model.py::TestBuildNodesEdges -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dashboard/graph_model.py tests/dashboard/test_graph_model.py
git commit -m "feat(v2c): build_graph - noeuds + aretes (topologie statique)"
```

---

## Task 8: `build_graph` — step assigné + QA pass (détail complet)

**Files:**
- Modify: `dashboard/graph_model.py` (`_active_path`, `_build_step`, `_meta_record`, `_events_by_task`, `build_graph`)
- Test: `tests/dashboard/test_graph_model.py`

- [ ] **Step 1: Écrire le test du step pass**

Ajouter à `tests/dashboard/test_graph_model.py` :

```python
from aaosa.tracing.store import SessionMeta, SessionTaskRecord
from datetime import datetime, timezone


def _meta(records):
    now = datetime.now(timezone.utc)
    return SessionMeta(
        session_id=SID, started_at=now, ended_at=now,
        tasks=records, agent_ids=["a", "b"],
    )


class TestBuildStepPass:
    def test_one_step_pass(self):
        meta = LLMMetadata(model_name="gpt-4o-mini", tokens_in=10, tokens_out=5, latency_ms=42.0)
        events = [
            p1("t1", "a", True, 0.9), p1("t1", "b", False, 0.2),
            p2("t1", "a", "claim", "css is mine"),
            disp("t1", "a", "highest fit"),
            ex("t1", "a", summary="fixed it", content="the full fix", meta=meta),
            qa("t1", "a", success=True, score=0.85, reason="good", criteria={"non_empty": True}),
            elo("t1", "a", {"css": 5}),
            tag("t1", "a", "hover", 50),
        ]
        sm = _meta([SessionTaskRecord(
            id="t1", description="Fix CSS hover", winner_agent_id="a",
            outcome="qa_pass", required_tags={"css": 60},
        )])
        model = build_graph(events, sm)

        assert len(model.steps) == 1
        step = model.steps[0]
        assert step.task_id == "t1"
        assert step.label == "Fix CSS hover"
        assert step.winner_agent_id == "a"
        assert step.outcome == "qa_pass"
        assert step.active_nodes == ["input", "dispatch", "a", "evaluator", "output"]
        active_pairs = [(e.from_node, e.to) for e in step.active_edges]
        assert active_pairs == [("input", "dispatch"), ("dispatch", "a"), ("a", "evaluator"), ("evaluator", "output")]

    def test_step_detail_pass(self):
        meta = LLMMetadata(model_name="gpt-4o-mini", tokens_in=10, tokens_out=5, latency_ms=42.0)
        events = [
            p1("t1", "a", True, 0.9), p1("t1", "b", False, 0.2),
            p2("t1", "a", "claim", "css is mine"),
            disp("t1", "a", "highest fit"),
            ex("t1", "a", summary="fixed", content="the full fix", meta=meta),
            qa("t1", "a", success=True, score=0.85, reason="good", criteria={"non_empty": True}),
            elo("t1", "a", {"css": 5}),
            tag("t1", "a", "hover", 50),
        ]
        sm = _meta([SessionTaskRecord(
            id="t1", description="Fix CSS hover", winner_agent_id="a",
            outcome="qa_pass", required_tags={"css": 60},
        )])
        d = build_graph(events, sm).steps[0].detail

        assert d.input.required_tags == {"css": 60}
        assert d.input.description == "Fix CSS hover"
        assert {c.agent_id for c in d.dispatch.candidates} == {"a", "b"}
        assert d.dispatch.winner_agent_id == "a"
        assert d.dispatch.dispatch_reason == "highest fit"
        assert len(d.dispatch.claims) == 1 and d.dispatch.claims[0].agent_id == "a"

        wa = d.agents["a"]
        assert wa.role == "winner"
        assert wa.fit_score == 0.9
        assert wa.claim_decision == "claim"
        assert wa.output_content == "the full fix"
        assert wa.llm_metadata.tokens_in == 10
        assert wa.elo_deltas == {"css": 5}
        assert wa.tags_acquired[0].tag == "hover"

        ca = d.agents["b"]
        assert ca.role == "candidate"
        assert ca.passed is False
        assert ca.output_content is None
        assert ca.elo_deltas == {}

        assert d.evaluator.ran is True
        assert d.evaluator.success is True
        assert d.evaluator.criteria_results == {"non_empty": True}
        assert d.output.produced is True
        assert d.output.output_content == "the full fix"
        assert d.testset.forked is False
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_graph_model.py::TestBuildStepPass -v`
Expected: FAIL — `model.steps` est vide (`build_graph` renvoie `steps=[]`).

- [ ] **Step 3: Implémenter le step + détail (chemin pass)**

Dans `dashboard/graph_model.py`, ajouter les helpers `_events_by_task`, `_meta_record`, `_order_task_ids`, `_active_path`, `_build_step`, puis recâbler `build_graph`. Remplacer la fonction `build_graph` du Task 7 par l'ensemble suivant :

```python
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
    input_detail = InputDetail(task_id=task_id, description=description, required_tags=required_tags)

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
```

- [ ] **Step 4: Lancer les tests step pass**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_graph_model.py::TestBuildStepPass -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dashboard/graph_model.py tests/dashboard/test_graph_model.py
git commit -m "feat(v2c): build_graph - step assigne + QA pass (detail complet)"
```

---

## Task 9: `build_graph` — variantes unassigned / no_qa / qa_fail

**Files:**
- Test: `tests/dashboard/test_graph_model.py`

> Le `_build_step` du Task 8 gère déjà ces branches. Ce task verrouille le comportement par des tests dédiés. Si une assertion échoue, corriger `_build_step` / `_active_path` en conséquence (et le noter).

- [ ] **Step 1: Écrire les tests des variantes**

Ajouter à `tests/dashboard/test_graph_model.py` :

```python
class TestBuildStepVariants:
    def test_unassigned(self):
        events = [p1("t1", "a", False, 0.1), p1("t1", "b", False, 0.1), unassigned("t1", "no candidate claimed")]
        step = build_graph(events).steps[0]
        assert step.outcome == "unassigned"
        assert step.winner_agent_id is None
        assert step.active_nodes == ["input", "dispatch"]
        assert [(e.from_node, e.to) for e in step.active_edges] == [("input", "dispatch")]
        assert step.detail.dispatch.unassigned_reason == "no candidate claimed"
        assert step.detail.evaluator.ran is False
        assert step.detail.output.produced is False

    def test_no_qa(self):
        events = [p1("t1", "a", True, 0.9), p2("t1", "a", "claim", "mine"),
                  disp("t1", "a"), ex("t1", "a", content="done")]
        step = build_graph(events).steps[0]
        assert step.outcome == "no_qa"
        assert step.winner_agent_id == "a"
        assert step.active_nodes == ["input", "dispatch", "a", "output"]
        assert [(e.from_node, e.to) for e in step.active_edges] == [("input", "dispatch"), ("dispatch", "a"), ("a", "output")]
        assert step.detail.evaluator.ran is False
        assert step.detail.output.produced is True

    def test_qa_fail_forks_to_testset(self):
        events = [p1("t1", "a", True, 0.9), p2("t1", "a", "claim", "mine"),
                  disp("t1", "a"), ex("t1", "a", content="weak"),
                  qa("t1", "a", success=False, score=0.3, reason="too short", criteria={"min_length": False})]
        step = build_graph(events).steps[0]
        assert step.outcome == "qa_fail"
        assert step.winner_agent_id == "a"
        assert step.active_nodes == ["input", "dispatch", "a", "evaluator", "testset"]
        assert [(e.from_node, e.to) for e in step.active_edges] == [("input", "dispatch"), ("dispatch", "a"), ("a", "evaluator"), ("evaluator", "testset")]
        assert step.detail.testset.forked is True
        assert step.detail.testset.from_task_id == "t1"
        assert step.detail.evaluator.success is False
        assert step.detail.output.produced is True  # output produit puis rejeté
```

- [ ] **Step 2: Lancer les tests**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_graph_model.py::TestBuildStepVariants -v`
Expected: PASS (logique déjà en place). Si un test échoue, corriger `_build_step`/`_active_path` puis relancer.

- [ ] **Step 3: Commit**

```bash
git add tests/dashboard/test_graph_model.py
git commit -m "test(v2c): build_graph - variantes unassigned/no_qa/qa_fail"
```

---

## Task 10: `build_graph` — session multi-task (ordre) + multi-claim

**Files:**
- Test: `tests/dashboard/test_graph_model.py`

> Couvre l'ordre des steps (meta-driven + fallback timestamp) et la résolution multi-claim. La logique est en place ; ce task la verrouille.

- [ ] **Step 1: Écrire les tests multi-task + multi-claim**

Ajouter à `tests/dashboard/test_graph_model.py` :

```python
from datetime import timedelta


class TestMultiTask:
    def test_steps_ordered_by_meta(self):
        events = (
            _single_pass_run(tid="t2", winner="a", others=("b",))
            + _single_pass_run(tid="t1", winner="b", others=("a",))
        )
        sm = _meta([
            SessionTaskRecord(id="t1", description="first", winner_agent_id="b", outcome="qa_pass", required_tags={"x": 1}),
            SessionTaskRecord(id="t2", description="second", winner_agent_id="a", outcome="qa_pass", required_tags={"y": 1}),
        ])
        steps = build_graph(events, sm).steps
        assert [s.task_id for s in steps] == ["t1", "t2"]
        assert [s.label for s in steps] == ["first", "second"]

    def test_steps_ordered_by_timestamp_when_no_meta(self):
        base = datetime(2026, 5, 29, 10, 0, 0, tzinfo=timezone.utc)
        e_early = p1("t1", "a", True, 0.9)
        e_early.timestamp = base
        e_late = p1("t2", "a", True, 0.9)
        e_late.timestamp = base + timedelta(seconds=10)
        # t2 apparait avant t1 dans la liste, mais t1 est plus tot
        steps = build_graph([e_late, e_early]).steps
        assert [s.task_id for s in steps] == ["t1", "t2"]

    def test_meta_label_fallback_to_task_id_when_no_meta(self):
        step = build_graph(_single_pass_run(tid="abc", winner="a", others=())).steps[0]
        assert step.label == "abc"
        assert step.detail.input.required_tags == {}

    def test_multi_claim_winner_from_dispatch(self):
        events = [
            p1("t1", "a", True, 0.8), p1("t1", "b", True, 0.7),
            p2("t1", "a", "claim", "a wants it"),
            p2("t1", "b", "claim", "b wants it"),
            disp("t1", "b", "b had higher score"),
            ex("t1", "b", content="b output"),
            qa("t1", "b", success=True),
        ]
        step = build_graph(events).steps[0]
        assert step.winner_agent_id == "b"
        assert len(step.detail.dispatch.claims) == 2
        assert step.detail.agents["a"].role == "candidate"
        assert step.detail.agents["b"].role == "winner"
```

- [ ] **Step 2: Lancer les tests**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_graph_model.py::TestMultiTask -v`
Expected: PASS. Si l'ordre par timestamp échoue, vérifier `_order_task_ids` (clé de tri = premier timestamp vu par task).

- [ ] **Step 3: Commit**

```bash
git add tests/dashboard/test_graph_model.py
git commit -m "test(v2c): build_graph - multi-task ordering + multi-claim"
```

---

## Task 11: `build_graph` — mode health check (N runs → dernier)

**Files:**
- Test: `tests/dashboard/test_graph_model.py`

> En health check : pas de `SessionMeta`, un seul `task_id` répété N fois (mode V1, donc pas d'`EloUpdatedEvent`/`TagAcquiredEvent`). Le collector (Épique 03a) pré-filtrera la trace au cas voulu ; ici on vérifie que `build_graph` ne retient que le dernier run et reste correct sans meta.

- [ ] **Step 1: Écrire les tests mode health check**

Ajouter à `tests/dashboard/test_graph_model.py` :

```python
class TestHealthCheckMode:
    def test_n_runs_keeps_last_run(self):
        # 3 runs du meme cas, sans meta, sans ELO (mode V1)
        def run(winner, success):
            return [p1("c1", "a", True, 0.8), p1("c1", "b", True, 0.6),
                    p2("c1", winner, "claim", "mine"),
                    disp("c1", winner), ex("c1", winner, content=f"{winner} out"),
                    qa("c1", winner, success=success)]
        events = run("a", False) + run("a", True) + run("b", True)
        model = build_graph(events)
        assert len(model.steps) == 1
        step = model.steps[0]
        assert step.winner_agent_id == "b"      # dernier run
        assert step.outcome == "qa_pass"
        assert step.detail.agents["b"].output_content == "b out"
        assert step.detail.agents["b"].elo_deltas == {}  # pas d'ELO en health check

    def test_health_check_unassigned_last_run(self):
        def ok_run():
            return [p1("c1", "a", True, 0.8), p2("c1", "a", "claim", "mine"),
                    disp("c1", "a"), ex("c1", "a", content="out"), qa("c1", "a", success=True)]
        def fail_run():
            return [p1("c1", "a", False, 0.1), unassigned("c1", "nobody claimed")]
        events = ok_run() + fail_run()
        step = build_graph(build_graph_events := events).steps[0]
        assert step.outcome == "unassigned"
        assert step.winner_agent_id is None

    def test_label_is_task_id_without_meta(self):
        events = [p1("c1", "a", True, 0.9), p2("c1", "a", "claim", "x"),
                  disp("c1", "a"), ex("c1", "a", content="o"), qa("c1", "a", success=True)]
        step = build_graph(events).steps[0]
        assert step.label == "c1"
```

- [ ] **Step 2: Lancer les tests**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_graph_model.py::TestHealthCheckMode -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/dashboard/test_graph_model.py
git commit -m "test(v2c): build_graph - mode health check (dernier run par cas)"
```

---

## Task 12: Vérification non-régression complète

**Files:** aucun (vérification).

- [ ] **Step 1: Lancer la suite complète**

Run: `.venv\Scripts\python -m pytest -q`
Expected: PASS. Compte attendu : 493 (Épique 01) + nouveaux tests de cette épique (≈ 3 output_content events + 1 runner + 2 QAResult.judge + 3 QAEvent + 1 runner + 1 health check + 2 store + ~30 graph_model) ≈ 535+ verts, 0 échec.

- [ ] **Step 2: Vérifier que `dashboard/` est bien collecté et que `runs/` reste gitignored**

Run: `.venv\Scripts\python -m pytest tests/dashboard/ -v`
Expected: tous les tests `test_graph_model.py` collectés et verts (confirme que le `conftest.py` racine résout l'import `dashboard`).

Run: `git status --porcelain runs/`
Expected: aucune sortie.

- [ ] **Step 3: Vérifier l'absence de cycle d'import à froid**

Run: `.venv\Scripts\python -c "import dashboard.graph_model; from aaosa.qa.protocol import QAResult; from aaosa.tracing.events import QAEvaluatedEvent; print('ok')"`
Expected: affiche `ok` sans `ImportError`.

---

## Self-Review

**Spec coverage (épique 02 + Section 2/3 de la spec V2c) :**
- `build_graph(events, session_meta)` fonction pure → Tasks 7-11 ; `dashboard/graph_model.py`, zéro effet de bord.
- GraphModel nodes/edges/steps conformes pour les 6 scénarios → assigned+pass (Task 8), unassigned/no_qa/fail (Task 9), multi-task + multi-claim (Task 10), health check N runs (Task 11).
- Layers TOP/CENTER/BOTTOM par type → Task 7 (`test_fixed_nodes_present`, `test_agent_nodes_bottom`).
- Mode session (steps ordonnés meta/timestamp) vs health check (1 run/cas) → Tasks 10-11.
- Aucun nœud V3 → topologie fixe 5 nœuds + agents (Task 7), pas de TaskDivider/Aggregateur/tools.
- D1 events = vérité → outcome/winner dérivés des events (`_build_step`, Task 8).
- D2 dernier run universel → `_segment_runs` (Task 6), validé session (no-op) + health check (Task 11).
- D3 pur sur (events, meta), label agent = agent_id → Task 7 (`test_agent_nodes_bottom`) ; enrichissement registry hors scope (Épique 03a).
- D4 pass_rate/sélection de cas hors build_graph → non implémenté ici par design (note dans le préambule).
- Overlay `detail` aligné Épique 4 → `StepDetail` typé complet (Task 5, peuplé Task 8).
- Enrichissements E1-E4 → Tasks 1-4 (output_content, QAResult.judge, QAEvaluatedEvent.criteria_results+judge, SessionTaskRecord.required_tags).

**Placeholder scan :** aucun TODO/TBD. Deux endroits délèguent à des fixtures du fichier existant (Task 2 mock judge, Task 3 Step 9 fixtures health check) avec instruction explicite de réutiliser le pattern présent — ce ne sont pas des placeholders de code à produire mais des points d'adaptation aux helpers locaux déjà testés.

**Type consistency :**
- `GraphEdge.from_node` (alias `"from"`) : construit par nom partout (`from_node=`), sérialisé par alias en Épique 03a. Cohérent Tasks 5-11.
- `Outcome` = `Literal["qa_pass","qa_fail","unassigned","no_qa"]` cohérent entre `graph_model.py` et `store.TaskOutcome`.
- `JudgeBreakdown(mode, overall, dimension_scores, reason)` identique entre définition (judge.py, Task 2) et usages (protocol.py, events.py, spec_evaluator.py, graph_model.py).
- `build_graph(events, session_meta=None)`, `_segment_runs`, `_build_step`, `_active_path`, `_build_nodes`, `_build_edges` : signatures stables entre Tasks 6-8 et usages Tasks 9-11.
- `_active_path` renvoie `(active_nodes, active_edges)` ordonnés ; les tests asservissent l'ordre exact des chemins (Tasks 8-9).
```