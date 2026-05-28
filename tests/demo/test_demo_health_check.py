import aaosa.demo.run_health_check as hc_demo_module
from aaosa.demo.run_health_check import build_demo_test_set, run_demo_health_check
from aaosa.qa.test_set import active_cases
from aaosa.schemas.output import LLMMetadata, Output


def _output_for(task, content="x" * 80):
    return Output(
        task_id=task.id, agent_id="a1", content=content,
        llm_metadata=LLMMetadata(model_name="m", tokens_in=1, tokens_out=1, latency_ms=1.0),
    )


class TestBuildDemoTestSet:
    def test_has_all_attribution_types(self):
        ts = build_demo_test_set()
        attributions = {c.attribution for c in ts.cases}
        assert attributions == {"agent", "task_spec", "evaluator", "unattributed"}

    def test_has_both_roles(self):
        ts = build_demo_test_set()
        roles = {c.role for c in ts.cases}
        assert "regression_guard" in roles
        assert "fix_target" in roles

    def test_active_cases_only_agent_and_guard(self):
        ts = build_demo_test_set()
        active = active_cases(ts)
        for c in active:
            assert c.role == "regression_guard" or c.attribution == "agent"

    def test_quarantined_cases_not_active(self):
        ts = build_demo_test_set()
        active_ids = {c.task.id for c in active_cases(ts)}
        for c in ts.cases:
            if c.attribution in ("task_spec", "evaluator", "unattributed"):
                assert c.task.id not in active_ids


class TestRunDemoHealthCheck:
    def test_runs_without_crash(self, monkeypatch):
        ts = build_demo_test_set()
        first_agent_id = None

        def fake_run_task(task, agents, client, **k):
            nonlocal first_agent_id
            if first_agent_id is None and agents:
                first_agent_id = agents[0].id
            return _output_for(task)

        monkeypatch.setattr(hc_demo_module, "create_client", lambda: object())
        monkeypatch.setattr(hc_demo_module, "run_task", fake_run_task)
        run_demo_health_check()

    def test_report_shows_all_quarantine_buckets(self, monkeypatch, capsys):
        def fake_run_task(task, agents, client, **k):
            return _output_for(task)

        monkeypatch.setattr(hc_demo_module, "create_client", lambda: object())
        monkeypatch.setattr(hc_demo_module, "run_task", fake_run_task)
        run_demo_health_check()

        out = capsys.readouterr().out
        assert "task_spec" in out
        assert "evaluator" in out
        assert "unattributed" in out
