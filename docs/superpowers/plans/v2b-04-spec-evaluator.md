# V2b Subtask 04 — SpecEvaluator (interprète la spec, combine gates/scored/judge)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development ou superpowers:executing-plans.

_Statut: TODO_
_Depends on: 01 (criteria/registry), 02 (spec), 03 (judge)_
_Blocking: 06 (health check), 09 (demo)_

## Objectif

Implémenter `SpecEvaluator` : interprète un `EvaluatorSpec`, applique l'algorithme gates → scored → judge, produit un `QAResult` (compatible `QAEvaluator` Protocol V2a). Plus la factory `from_spec`. La référence du judge est portée par l'instance (construction), pas par le Protocol → signature `evaluate(task, output)` stable.

## Méthode

TDD strict. Le judge est testé par **monkeypatch** de `run_judge` (pas d'appel LLM).

## Fichiers

| Fichier | Action |
|---|---|
| `src/aaosa/qa/spec_evaluator.py` | CRÉER |
| `tests/qa/test_spec_evaluator.py` | CRÉER |

## Verification finale

```powershell
.venv\Scripts\python -m pytest tests/qa/test_spec_evaluator.py -v
.venv\Scripts\python -m pytest tests/ -v
```

---

## Context — QAResult (V2a, inchangé) et algo cible

```python
# src/aaosa/qa/protocol.py
class QAResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str
    agent_id: str
    success: bool
    score: float
    reason: str
    criteria_results: dict[str, bool]

@runtime_checkable
class QAEvaluator(Protocol):
    def evaluate(self, task: Task, output: Output) -> QAResult: ...
```

Algorithme (spec §1.7) :

```
1. Gates (ordre de la spec) : si un gate échoue → QAResult(success=False, score=0.0,
   reason="gate failed: <name>", criteria_results={gates évalués}). Judge sauté.
2. Scorés : det_score = somme(score*weight)/somme(weight) ; 1.0 si aucun scoré.
3. Judge (si spec.judge) : final = (1-w)*det_score + w*judge.overall ; sinon final = det_score.
4. success = final >= success_threshold.
```

---

## Étape 1 — Tests (RED)

Créer `tests/qa/test_spec_evaluator.py`.

```python
import pytest

import aaosa.qa.spec_evaluator as se_module
from aaosa.qa.judge import JudgeResult
from aaosa.qa.protocol import QAEvaluator, QAResult
from aaosa.qa.spec import CriterionSpec, EvaluatorSpec, JudgeSpec
from aaosa.qa.spec_evaluator import SpecEvaluator, from_spec
from aaosa.schemas.output import Output, LLMMetadata
from aaosa.schemas.task import Task


def make_task() -> Task:
    return Task(description="do x", required_tags={"python": 80})


def make_output(content: str) -> Output:
    return Output(
        task_id="t1", agent_id="a1", content=content,
        llm_metadata=LLMMetadata(model_name="m", tokens_in=1, tokens_out=1, latency_ms=1.0),
    )


class TestProtocolCompliance:
    def test_satisfies_qaevaluator(self):
        ev = SpecEvaluator(EvaluatorSpec(criteria=[CriterionSpec(name="non_empty", gate=True)]))
        assert isinstance(ev, QAEvaluator)

    def test_returns_qaresult(self):
        ev = SpecEvaluator(EvaluatorSpec(criteria=[CriterionSpec(name="non_empty", gate=True)]))
        r = ev.evaluate(make_task(), make_output("hello world"))
        assert isinstance(r, QAResult)
        assert r.task_id == make_task().id or r.task_id  # task_id renseigné


class TestGates:
    def test_gate_fail_short_circuits(self):
        spec = EvaluatorSpec(criteria=[CriterionSpec(name="non_empty", gate=True)])
        r = SpecEvaluator(spec).evaluate(make_task(), make_output(""))
        assert r.success is False
        assert r.score == 0.0
        assert "gate failed" in r.reason
        assert r.criteria_results["non_empty"] is False

    def test_all_gates_pass(self):
        spec = EvaluatorSpec(criteria=[CriterionSpec(name="non_empty", gate=True)],
                             success_threshold=0.5)
        r = SpecEvaluator(spec).evaluate(make_task(), make_output("hello"))
        assert r.success is True


class TestScoredCombination:
    def test_weighted_average(self):
        # min_length scoré (content 25 chars → score 0.5) avec seuil 0.4 → success
        spec = EvaluatorSpec(
            criteria=[CriterionSpec(name="min_length", weight=1.0)],
            success_threshold=0.4,
        )
        r = SpecEvaluator(spec).evaluate(make_task(), make_output("x" * 25))
        assert r.score == pytest.approx(0.5)
        assert r.success is True

    def test_no_scored_criteria_score_is_one(self):
        spec = EvaluatorSpec(criteria=[CriterionSpec(name="non_empty", gate=True)],
                             success_threshold=0.9)
        r = SpecEvaluator(spec).evaluate(make_task(), make_output("hello"))
        assert r.score == pytest.approx(1.0)
        assert r.success is True

    def test_threshold_not_met(self):
        spec = EvaluatorSpec(
            criteria=[CriterionSpec(name="min_length", weight=1.0)],
            success_threshold=0.9,
        )
        r = SpecEvaluator(spec).evaluate(make_task(), make_output("x" * 25))  # score 0.5
        assert r.success is False


class TestJudgeCombination:
    def test_judge_combined_linearly(self, monkeypatch):
        # det_score = 1.0 (min_length pass, 60 chars), judge.overall = 0.0, weight 0.5 → final 0.5
        monkeypatch.setattr(
            se_module, "run_judge",
            lambda task, output, spec, client, reference=None: JudgeResult(
                dimension_scores={"correctness": 0.0}, overall=0.0, reason="bad"),
        )
        spec = EvaluatorSpec(
            criteria=[CriterionSpec(name="min_length", weight=1.0)],
            judge=JudgeSpec(rubric=["correctness"], weight=0.5),
            success_threshold=0.6,
        )
        r = SpecEvaluator(spec, client=object()).evaluate(make_task(), make_output("x" * 60))
        assert r.score == pytest.approx(0.5)   # (1-0.5)*1.0 + 0.5*0.0
        assert r.success is False               # 0.5 < 0.6

    def test_judge_skipped_when_gate_fails(self, monkeypatch):
        called = {"n": 0}
        def _spy(*a, **k):
            called["n"] += 1
            return JudgeResult(dimension_scores={}, overall=1.0, reason="")
        monkeypatch.setattr(se_module, "run_judge", _spy)
        spec = EvaluatorSpec(
            criteria=[CriterionSpec(name="non_empty", gate=True)],
            judge=JudgeSpec(rubric=["x"], weight=0.5),
        )
        SpecEvaluator(spec, client=object()).evaluate(make_task(), make_output(""))
        assert called["n"] == 0   # judge jamais appelé si gate échoue

    def test_reference_passed_to_judge(self, monkeypatch):
        seen = {}
        def _capture(task, output, spec, client, reference=None):
            seen["reference"] = reference
            return JudgeResult(dimension_scores={}, overall=1.0, reason="")
        monkeypatch.setattr(se_module, "run_judge", _capture)
        spec = EvaluatorSpec(
            criteria=[CriterionSpec(name="non_empty", gate=True)],
            judge=JudgeSpec(mode="reference_based", rubric=["x"]),
            success_threshold=0.5,
        )
        SpecEvaluator(spec, client=object(), reference="IDEAL").evaluate(make_task(), make_output("hi"))
        assert seen["reference"] == "IDEAL"


class TestConstruction:
    def test_judge_without_client_raises(self):
        spec = EvaluatorSpec(
            criteria=[CriterionSpec(name="non_empty", gate=True)],
            judge=JudgeSpec(rubric=["x"]),
        )
        with pytest.raises(ValueError, match="client"):
            SpecEvaluator(spec, client=None)

    def test_from_spec_returns_evaluator(self):
        ev = from_spec(EvaluatorSpec(criteria=[CriterionSpec(name="non_empty", gate=True)]))
        assert isinstance(ev, SpecEvaluator)
```

- [ ] **Step 1: Écrire les tests**
- [ ] **Step 2: RED** — `.venv\Scripts\python -m pytest tests/qa/test_spec_evaluator.py -v`

---

## Étape 2 — Implementation (GREEN)

Créer `src/aaosa/qa/spec_evaluator.py`.

```python
from openai import OpenAI

from aaosa.qa.criteria import get_criterion
from aaosa.qa.judge import run_judge
from aaosa.qa.protocol import QAResult
from aaosa.qa.spec import EvaluatorSpec
from aaosa.schemas.output import Output
from aaosa.schemas.task import Task


class SpecEvaluator:
    def __init__(
        self,
        spec: EvaluatorSpec,
        client: OpenAI | None = None,
        reference: str | None = None,
    ):
        if spec.judge is not None and client is None:
            raise ValueError("spec has a judge but no client was provided")
        self.spec = spec
        self.client = client
        self.reference = reference

    def evaluate(self, task: Task, output: Output) -> QAResult:
        criteria_results: dict[str, bool] = {}

        # 1. Gates (ordre de la spec)
        for c in self.spec.criteria:
            if not c.gate:
                continue
            outcome = get_criterion(c.name)(task, output, c.params)
            criteria_results[outcome.name] = outcome.passed
            if not outcome.passed:
                return QAResult(
                    task_id=task.id, agent_id=output.agent_id,
                    success=False, score=0.0,
                    reason=f"gate failed: {c.name} ({outcome.detail})",
                    criteria_results=criteria_results,
                )

        # 2. Critères scorés
        scored = [c for c in self.spec.criteria if not c.gate]
        if scored:
            total_weight = sum(c.weight for c in scored)
            weighted = 0.0
            for c in scored:
                outcome = get_criterion(c.name)(task, output, c.params)
                criteria_results[outcome.name] = outcome.passed
                weighted += outcome.score * c.weight
            det_score = weighted / total_weight if total_weight > 0 else 1.0
        else:
            det_score = 1.0

        # 3. Judge
        reason = "deterministic criteria evaluated"
        if self.spec.judge is not None:
            judge_result = run_judge(
                task, output, self.spec.judge, self.client, self.reference
            )
            w = self.spec.judge.weight
            final = (1.0 - w) * det_score + w * judge_result.overall
            reason = f"det={det_score:.2f} judge={judge_result.overall:.2f} ({judge_result.reason})"
        else:
            final = det_score

        # 4. Verdict
        return QAResult(
            task_id=task.id, agent_id=output.agent_id,
            success=final >= self.spec.success_threshold,
            score=final, reason=reason, criteria_results=criteria_results,
        )


def from_spec(
    spec: EvaluatorSpec,
    client: OpenAI | None = None,
    reference: str | None = None,
) -> SpecEvaluator:
    return SpecEvaluator(spec, client=client, reference=reference)
```

- [ ] **Step 3: Écrire `spec_evaluator.py`**
- [ ] **Step 4: GREEN** — `.venv\Scripts\python -m pytest tests/qa/test_spec_evaluator.py -v`
- [ ] **Step 5: Suite complète** — `.venv\Scripts\python -m pytest tests/ -v`
- [ ] **Step 6: Commit** — `git add src/aaosa/qa/spec_evaluator.py tests/qa/test_spec_evaluator.py && git commit -m "feat(v2b): SpecEvaluator (gates/scored/judge) + from_spec"`

## Invariants

- Imports absolus. `run_judge` importé au niveau module (monkeypatchable par les tests).
- Judge **jamais** appelé si un gate échoue.
- `det_score`, `final ∈ [0.0, 1.0]`.
- `ValueError` si `spec.judge` présent mais `client is None` (à la construction).
- `SpecEvaluator` satisfait `QAEvaluator` (structural typing — signature `evaluate(task, output)` inchangée).
- La référence vient de la construction, jamais de `evaluate`.
- `task_id`/`agent_id` du `QAResult` viennent de `task.id` / `output.agent_id`.
