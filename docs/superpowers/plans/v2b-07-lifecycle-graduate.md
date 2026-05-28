# V2b Subtask 07 — Lifecycle (graduate)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development ou superpowers:executing-plans.

_Statut: TODO_
_Depends on: 05 (TestSet/TestCase), 06 (HealthCheckReport/CaseResult)_
_Blocking: —_

## Objectif

Implémenter `graduate(test_set, report, graduation_threshold=0.8)` : promeut en `regression_guard` les `fix_target` dont le `case_pass_rate` (sur N runs) atteint le seuil. La graduation repose sur le **taux**, pas une passe unique. Un cas `unstable` ne gradúe jamais (son pass_rate 0.4-0.6 < 0.8). `active_cases` est déjà livré en subtask 05.

## Méthode

TDD strict. Fonction pure : construit un nouveau `TestSet` (ne mute pas l'entrée).

## Fichiers

| Fichier | Action |
|---|---|
| `src/aaosa/qa/lifecycle.py` | CRÉER |
| `tests/qa/test_lifecycle.py` | CRÉER |

## Verification finale

```powershell
.venv\Scripts\python -m pytest tests/qa/test_lifecycle.py -v
.venv\Scripts\python -m pytest tests/ -v
```

---

## Context

```python
# TestCase / TestSet (qa/test_set.py, subtask 05) — TestCase a .task.id, .role
# CaseResult (qa/health_check.py, subtask 06) — .task_id, .pass_rate
# HealthCheckReport (qa/health_check.py) — .case_results: list[CaseResult]
```

Règle : pour chaque `fix_target` du test set, si un `CaseResult` du rapport (matché par `task.id`) a `pass_rate >= graduation_threshold`, on le promeut en `regression_guard`. Les autres cas (regression_guard, fix_target non atteints, cas absents du rapport) sont conservés tels quels.

---

## Étape 1 — Tests (RED)

Créer `tests/qa/test_lifecycle.py`.

```python
from datetime import datetime, timezone

from aaosa.qa.health_check import CaseResult, HealthCheckReport
from aaosa.qa.lifecycle import graduate
from aaosa.qa.spec import CriterionSpec, EvaluatorSpec
from aaosa.qa.test_set import TestCase, TestSet
from aaosa.schemas.task import Task


def make_task(desc="x") -> Task:
    return Task(description=desc, required_tags={"python": 80})


def spec() -> EvaluatorSpec:
    return EvaluatorSpec(criteria=[CriterionSpec(name="non_empty", gate=True)])


def fix_target(task) -> TestCase:
    return TestCase(task=task, evaluator_spec=spec(), origin="runtime_failure",
                    role="fix_target", attribution="agent")


def guard(task) -> TestCase:
    return TestCase(task=task, evaluator_spec=spec(), origin="curated", role="regression_guard")


def report_with(case_results) -> HealthCheckReport:
    return HealthCheckReport(
        timestamp=datetime.now(timezone.utc), n_runs=5, total_cases=len(case_results),
        case_results=case_results, fix_target_pass_rate=0.0, regression_guard_pass_rate=0.0,
        unstable_cases=[], unattributed=[],
    )


def cr(task_id, role, pass_rate) -> CaseResult:
    return CaseResult(task_id=task_id, role=role, n_runs=5,
                      pass_count=round(pass_rate * 5), pass_rate=pass_rate,
                      unstable=0.4 <= pass_rate <= 0.6, qa_results=[], qa_failures=[])


def role_of(ts: TestSet, task_id: str) -> str:
    return next(c.role for c in ts.cases if c.task.id == task_id)


class TestGraduate:
    def test_fix_target_graduates_above_threshold(self):
        task = make_task()
        ts = TestSet(cases=[fix_target(task)])
        report = report_with([cr(task.id, "fix_target", 1.0)])
        out = graduate(ts, report)
        assert role_of(out, task.id) == "regression_guard"

    def test_fix_target_stays_below_threshold(self):
        task = make_task()
        ts = TestSet(cases=[fix_target(task)])
        report = report_with([cr(task.id, "fix_target", 0.6)])
        out = graduate(ts, report)
        assert role_of(out, task.id) == "fix_target"

    def test_boundary_exactly_threshold_graduates(self):
        task = make_task()
        ts = TestSet(cases=[fix_target(task)])
        report = report_with([cr(task.id, "fix_target", 0.8)])
        out = graduate(ts, report)
        assert role_of(out, task.id) == "regression_guard"

    def test_custom_threshold(self):
        task = make_task()
        ts = TestSet(cases=[fix_target(task)])
        report = report_with([cr(task.id, "fix_target", 1.0)])
        out = graduate(ts, report, graduation_threshold=1.0)
        assert role_of(out, task.id) == "regression_guard"

    def test_guard_unchanged(self):
        task = make_task()
        ts = TestSet(cases=[guard(task)])
        report = report_with([cr(task.id, "regression_guard", 1.0)])
        out = graduate(ts, report)
        assert role_of(out, task.id) == "regression_guard"

    def test_case_absent_from_report_unchanged(self):
        task = make_task()
        ts = TestSet(cases=[fix_target(task)])
        out = graduate(ts, report_with([]))
        assert role_of(out, task.id) == "fix_target"

    def test_does_not_mutate_input(self):
        task = make_task()
        ts = TestSet(cases=[fix_target(task)])
        report = report_with([cr(task.id, "fix_target", 1.0)])
        graduate(ts, report)
        assert ts.cases[0].role == "fix_target"   # entrée inchangée

    def test_unstable_does_not_graduate(self):
        task = make_task()
        ts = TestSet(cases=[fix_target(task)])
        report = report_with([cr(task.id, "fix_target", 0.5)])  # unstable
        out = graduate(ts, report)
        assert role_of(out, task.id) == "fix_target"
```

- [ ] **Step 1: Écrire les tests**
- [ ] **Step 2: RED** — `.venv\Scripts\python -m pytest tests/qa/test_lifecycle.py -v`

---

## Étape 2 — Implementation (GREEN)

Créer `src/aaosa/qa/lifecycle.py`.

```python
from aaosa.qa.health_check import HealthCheckReport
from aaosa.qa.test_set import TestCase, TestSet


def graduate(
    test_set: TestSet,
    report: HealthCheckReport,
    graduation_threshold: float = 0.8,
) -> TestSet:
    """Promeut en regression_guard les fix_target dont le case_pass_rate (sur N runs)
    atteint graduation_threshold. Fonction pure : retourne un nouveau TestSet."""
    rate_by_task = {c.task_id: c.pass_rate for c in report.case_results}

    new_cases: list[TestCase] = []
    for case in test_set.cases:
        if (
            case.role == "fix_target"
            and rate_by_task.get(case.task.id, 0.0) >= graduation_threshold
        ):
            new_cases.append(case.model_copy(update={"role": "regression_guard"}))
        else:
            new_cases.append(case)

    return TestSet(cases=new_cases)
```

- [ ] **Step 3: Écrire `lifecycle.py`**
- [ ] **Step 4: GREEN** — `.venv\Scripts\python -m pytest tests/qa/test_lifecycle.py -v`
- [ ] **Step 5: Suite complète** — `.venv\Scripts\python -m pytest tests/ -v`
- [ ] **Step 6: Commit** — `git add src/aaosa/qa/lifecycle.py tests/qa/test_lifecycle.py && git commit -m "feat(v2b): lifecycle graduate (fix_target -> regression_guard par taux)"`

## Invariants

- Imports absolus.
- Fonction **pure** : ne mute pas le `test_set` d'entrée (`model_copy` pour la promotion).
- Graduation par **taux** (`pass_rate >= threshold`), jamais sur une passe unique.
- Comparaison `>=` (le seuil exact gradúe).
- Un cas absent du rapport est conservé tel quel (pass_rate défaut 0.0).
- Un cas `unstable` (0.4-0.6) ne gradúe pas avec le défaut 0.8.
- Seuls les `fix_target` peuvent graduer ; les `regression_guard` restent guards.
