# V2b Subtask 06 — Health check refactor (TestSet, N runs, CaseResult)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development ou superpowers:executing-plans.

_Statut: TODO_
_Depends on: 04 (from_spec/SpecEvaluator), 05 (TestSet, active_cases)_
_Blocking: 07 (lifecycle), 09 (demo)_

## Objectif

Refactorer `run_health_check` : prend un `TestSet` (au lieu de `list[tuple[Task, QAEvaluator]]`), tourne **chaque cas actif `n_runs` fois** (le non-déterminisme de l'agent fait qu'un passage unique est un échantillon bruité), produit un `CaseResult` par cas (taux de réussite, flag `unstable`) et un `HealthCheckReport` enrichi (pass-rates par `role`). Read-only sur l'ELO (décision V2a conservée).

## Méthode

TDD strict. `run_task` est **monkeypatché** (pas d'appel LLM) ; l'évaluation utilise un `SpecEvaluator` déterministe (sans judge).

## ⚠️ Refactor — breaking interne assumé

La V2a `health_check.py` définit `TestCase = tuple[Task, QAEvaluator]` et un `HealthCheckReport` simple. On **remplace** la signature. Les anciens tests `tests/qa/test_health_check.py` V2a sont **réécrits** dans ce subtask (pas conservés).

## Fichiers

| Fichier | Action |
|---|---|
| `src/aaosa/qa/health_check.py` | RÉÉCRIRE |
| `tests/qa/test_health_check.py` | RÉÉCRIRE |

## Verification finale

```powershell
.venv\Scripts\python -m pytest tests/qa/test_health_check.py -v
.venv\Scripts\python -m pytest tests/ -v
```

---

## Context

```python
# run_task (runtime/runner.py) — appelé en mode V1 (sans evaluator) → read-only ELO
def run_task(task, agents, client, tracer=None, evaluator=None) -> Output | DispatchResult | QAFailure

# DispatchResult (claiming/dispatch.py) : a un champ .status ("assigned" | "unassigned")
# Output (schemas/output.py) : task_id, agent_id, content, llm_metadata, timestamp
# from_spec (qa/spec_evaluator.py), active_cases + TestSet + TestCase (qa/test_set.py)
# QAResult, QAFailure (qa/protocol.py)
# QAEvaluatedEvent (tracing/events.py) : session_id, task_id, agent_id, success, score, reason
```

---

## Étape 1 — Tests (RED)

Créer `tests/qa/test_health_check.py` (réécriture).

```python
import aaosa.qa.health_check as hc_module
from aaosa.qa.health_check import CaseResult, HealthCheckReport, run_health_check
from aaosa.qa.spec import CriterionSpec, EvaluatorSpec
from aaosa.qa.test_set import TestCase, TestSet
from aaosa.schemas.output import Output, LLMMetadata
from aaosa.schemas.task import Task


def make_task(desc="do x") -> Task:
    return Task(description=desc, required_tags={"python": 80})


def passing_output(task) -> Output:
    return Output(
        task_id=task.id, agent_id="a1", content="x" * 80,   # min_length pass
        llm_metadata=LLMMetadata(model_name="m", tokens_in=1, tokens_out=1, latency_ms=1.0),
    )


def failing_output(task) -> Output:
    return Output(
        task_id=task.id, agent_id="a1", content="",           # non_empty gate fail
        llm_metadata=LLMMetadata(model_name="m", tokens_in=1, tokens_out=1, latency_ms=1.0),
    )


# Spec déterministe : gate non_empty + min_length scoré, seuil bas
def det_spec() -> EvaluatorSpec:
    return EvaluatorSpec(
        criteria=[CriterionSpec(name="non_empty", gate=True),
                  CriterionSpec(name="min_length", weight=1.0)],
        success_threshold=0.5,
    )


def guard_case(task, spec=None) -> TestCase:
    return TestCase(task=task, evaluator_spec=spec or det_spec(),
                    origin="curated", role="regression_guard")


class _Dispatch:
    status = "unassigned"


def patch_run_task(monkeypatch, fn):
    monkeypatch.setattr(hc_module, "run_task", fn)


class TestCaseResultSchema:
    def test_fields(self):
        cr = CaseResult(task_id="t", role="regression_guard", n_runs=5,
                        pass_count=3, pass_rate=0.6, unstable=False,
                        qa_results=[], qa_failures=[])
        assert cr.pass_rate == 0.6


class TestRunHealthCheck:
    def test_all_pass(self, monkeypatch):
        task = make_task()
        patch_run_task(monkeypatch, lambda *a, **k: passing_output(task))
        report = run_health_check([], TestSet(cases=[guard_case(task)]), client=object(), n_runs=3)
        assert report.total_cases == 1
        assert report.case_results[0].pass_rate == 1.0
        assert report.regression_guard_pass_rate == 1.0

    def test_all_fail(self, monkeypatch):
        task = make_task()
        patch_run_task(monkeypatch, lambda *a, **k: failing_output(task))
        report = run_health_check([], TestSet(cases=[guard_case(task)]), client=object(), n_runs=3)
        assert report.case_results[0].pass_rate == 0.0
        assert len(report.case_results[0].qa_failures) == 3

    def test_pass_rate_over_n_runs(self, monkeypatch):
        task = make_task()
        seq = [passing_output(task), failing_output(task), passing_output(task),
               failing_output(task), passing_output(task)]
        it = iter(seq)
        patch_run_task(monkeypatch, lambda *a, **k: next(it))
        report = run_health_check([], TestSet(cases=[guard_case(task)]), client=object(), n_runs=5)
        cr = report.case_results[0]
        assert cr.pass_count == 3 and cr.n_runs == 5
        assert cr.pass_rate == 0.6

    def test_unstable_flag(self, monkeypatch):
        task = make_task()
        seq = [passing_output(task), failing_output(task)]   # 1/2 = 0.5 → unstable
        it = iter(seq)
        patch_run_task(monkeypatch, lambda *a, **k: next(it))
        report = run_health_check([], TestSet(cases=[guard_case(task)]), client=object(), n_runs=2)
        assert report.case_results[0].unstable is True
        assert task.id in report.unstable_cases

    def test_dispatch_result_counts_as_fail_run(self, monkeypatch):
        task = make_task()
        patch_run_task(monkeypatch, lambda *a, **k: _Dispatch())
        report = run_health_check([], TestSet(cases=[guard_case(task)]), client=object(), n_runs=2)
        assert report.case_results[0].pass_rate == 0.0

    def test_only_active_cases_evaluated(self, monkeypatch):
        task = make_task()
        patch_run_task(monkeypatch, lambda *a, **k: passing_output(task))
        ts = TestSet(cases=[
            guard_case(task),
            TestCase(task=make_task("quarantined"), evaluator_spec=det_spec(),
                     origin="runtime_failure", role="fix_target", attribution="task_spec"),
        ])
        report = run_health_check([], ts, client=object(), n_runs=1)
        assert report.total_cases == 1   # quarantine exclue

    def test_unattributed_listed(self, monkeypatch):
        task = make_task()
        unattr_task = make_task("needs triage")
        patch_run_task(monkeypatch, lambda *a, **k: passing_output(task))
        ts = TestSet(cases=[
            guard_case(task),
            TestCase(task=unattr_task, evaluator_spec=det_spec(),
                     origin="runtime_failure", role="fix_target", attribution="unattributed"),
        ])
        report = run_health_check([], ts, client=object(), n_runs=1)
        assert unattr_task.id in report.unattributed

    def test_pass_rates_split_by_role(self, monkeypatch):
        guard_t = make_task("guard")
        fix_t = make_task("fix")
        def fake(task, *a, **k):
            return passing_output(task) if task.description == "guard" else failing_output(task)
        patch_run_task(monkeypatch, fake)
        ts = TestSet(cases=[
            guard_case(guard_t),
            TestCase(task=fix_t, evaluator_spec=det_spec(),
                     origin="runtime_failure", role="fix_target", attribution="agent"),
        ])
        report = run_health_check([], ts, client=object(), n_runs=2)
        assert report.regression_guard_pass_rate == 1.0
        assert report.fix_target_pass_rate == 0.0

    def test_tracer_optional(self, monkeypatch):
        task = make_task()
        patch_run_task(monkeypatch, lambda *a, **k: passing_output(task))
        # ne doit pas lever sans tracer
        run_health_check([], TestSet(cases=[guard_case(task)]), client=object(), n_runs=1)
```

- [ ] **Step 1: Écrire les tests**
- [ ] **Step 2: RED** — `.venv\Scripts\python -m pytest tests/qa/test_health_check.py -v`

---

## Étape 2 — Implementation (GREEN)

Réécrire `src/aaosa/qa/health_check.py`.

```python
from datetime import datetime, timezone
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel, ConfigDict

from aaosa.core.agent import Agent
from aaosa.qa.protocol import QAFailure, QAResult
from aaosa.qa.spec_evaluator import from_spec
from aaosa.qa.test_set import TestSet, active_cases
from aaosa.runtime.runner import run_task
from aaosa.schemas.output import Output
from aaosa.tracing.events import QAEvaluatedEvent
from aaosa.tracing.tracer import Tracer


class CaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str
    role: Literal["fix_target", "regression_guard"]
    n_runs: int
    pass_count: int
    pass_rate: float
    unstable: bool
    qa_results: list[QAResult]
    qa_failures: list[QAFailure]


class HealthCheckReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timestamp: datetime
    n_runs: int
    total_cases: int
    case_results: list[CaseResult]
    fix_target_pass_rate: float
    regression_guard_pass_rate: float
    unstable_cases: list[str]
    unattributed: list[str]


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def run_health_check(
    agents: list[Agent],
    test_set: TestSet,
    client: OpenAI,
    n_runs: int = 5,
    tracer: Tracer | None = None,
) -> HealthCheckReport:
    case_results: list[CaseResult] = []

    for case in active_cases(test_set):
        evaluator = from_spec(case.evaluator_spec, client=client, reference=case.reference)
        pass_count = 0
        qa_results: list[QAResult] = []
        qa_failures: list[QAFailure] = []

        for _ in range(n_runs):
            result = run_task(case.task, agents, client, tracer=tracer)  # mode V1, read-only ELO
            if not isinstance(result, Output):
                # cas non assigné (DispatchResult) : compté comme run échoué, pas de QAResult
                continue
            qa = evaluator.evaluate(case.task, result)
            qa_results.append(qa)
            if tracer is not None:
                tracer.emit(QAEvaluatedEvent(
                    session_id=tracer.session_id, task_id=case.task.id,
                    agent_id=result.agent_id, success=qa.success,
                    score=qa.score, reason=qa.reason,
                ))
            if qa.success:
                pass_count += 1
            else:
                qa_failures.append(QAFailure(
                    task_id=case.task.id, agent_id=result.agent_id,
                    output=result, qa_result=qa,
                ))

        pass_rate = pass_count / n_runs if n_runs > 0 else 0.0
        case_results.append(CaseResult(
            task_id=case.task.id, role=case.role, n_runs=n_runs,
            pass_count=pass_count, pass_rate=pass_rate,
            unstable=0.4 <= pass_rate <= 0.6,
            qa_results=qa_results, qa_failures=qa_failures,
        ))

    guard_rates = [c.pass_rate for c in case_results if c.role == "regression_guard"]
    fix_rates = [c.pass_rate for c in case_results if c.role == "fix_target"]

    return HealthCheckReport(
        timestamp=datetime.now(timezone.utc),
        n_runs=n_runs,
        total_cases=len(case_results),
        case_results=case_results,
        fix_target_pass_rate=_mean(fix_rates),
        regression_guard_pass_rate=_mean(guard_rates),
        unstable_cases=[c.task_id for c in case_results if c.unstable],
        unattributed=[c.task.id for c in test_set.cases if c.attribution == "unattributed"],
    )
```

- [ ] **Step 3: Réécrire `health_check.py`**
- [ ] **Step 4: GREEN** — `.venv\Scripts\python -m pytest tests/qa/test_health_check.py -v`
- [ ] **Step 5: Suite complète** — `.venv\Scripts\python -m pytest tests/ -v`
- [ ] **Step 6: Commit** — `git add src/aaosa/qa/health_check.py tests/qa/test_health_check.py && git commit -m "refactor(v2b): health check sur TestSet, N runs, CaseResult + pass-rates par role"`

## Invariants

- Imports absolus. `run_task` importé au niveau module (monkeypatchable).
- Read-only sur l'ELO : `run_task` appelé **sans** `evaluator` (mode V1).
- Chaque cas actif tourne `n_runs` fois ; métrique = `pass_rate` (jamais pass/fail unique).
- `unstable` ⟺ `0.4 <= pass_rate <= 0.6`.
- Un `DispatchResult` (non assigné) compte comme run échoué (n'incrémente pas `pass_count`).
- Seuls les `active_cases` sont évalués ; `unattributed` est listé pour triage mais pas évalué.
- `tracer` optionnel.
- Aucun warning de collecte pytest (les modèles `TestSet`/`TestCase` portent `__test__ = False`, cf subtask 05).
