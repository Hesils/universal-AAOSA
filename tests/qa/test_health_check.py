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

    def test_task_spec_quarantine_listed(self, monkeypatch):
        task = make_task()
        qs_task = make_task("bad spec")
        patch_run_task(monkeypatch, lambda *a, **k: passing_output(task))
        ts = TestSet(cases=[
            guard_case(task),
            TestCase(task=qs_task, evaluator_spec=det_spec(),
                     origin="runtime_failure", role="fix_target", attribution="task_spec"),
        ])
        report = run_health_check([], ts, client=object(), n_runs=1)
        assert qs_task.id in report.task_spec_quarantined
        assert qs_task.id not in report.unattributed

    def test_evaluator_quarantine_listed(self, monkeypatch):
        task = make_task()
        qe_task = make_task("bad evaluator")
        patch_run_task(monkeypatch, lambda *a, **k: passing_output(task))
        ts = TestSet(cases=[
            guard_case(task),
            TestCase(task=qe_task, evaluator_spec=det_spec(),
                     origin="runtime_failure", role="fix_target", attribution="evaluator"),
        ])
        report = run_health_check([], ts, client=object(), n_runs=1)
        assert qe_task.id in report.evaluator_quarantined
        assert qe_task.id not in report.unattributed
