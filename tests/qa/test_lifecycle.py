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
