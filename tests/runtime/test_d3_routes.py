from types import SimpleNamespace

import aaosa.runtime.runner as runner
from aaosa.qa.diagnostic import DiagnosticResult
from aaosa.qa.protocol import QAFailure, QAResult
from aaosa.runtime.context import RunContext
from aaosa.schemas.output import LLMMetadata, Output
from aaosa.schemas.task import Task


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
    """ctx.agents doit couvrir les tags requis pour passer le roster gap."""
    def __init__(self):
        self.tags_with_elo = {"python": 50}


def _ctx(evaluator=None) -> RunContext:
    return RunContext(
        agents=[_StubAgentRoster()], client=SimpleNamespace(), divider=SimpleNamespace(),
        aggregator=SimpleNamespace(), tagger=SimpleNamespace(), tracer=None, evaluator=evaluator,
    )


def test_route_agent_retry_succeeds(monkeypatch):
    # 1er run_task → qa_fail ; retry → Output
    calls = [_qa_fail(), _output("good")]
    monkeypatch.setattr(runner, "run_task", lambda *a, **k: calls.pop(0))
    monkeypatch.setattr(runner, "diagnose_failure",
                        lambda *a, **k: DiagnosticResult(attribution="agent", consignes="be precise", reason="r"))
    out = runner.run_with_recovery(_task(), _ctx())
    assert isinstance(out, Output)
    assert out.content == "good"


def test_route_agent_retry_fails(monkeypatch):
    calls = [_qa_fail(), _qa_fail()]
    monkeypatch.setattr(runner, "run_task", lambda *a, **k: calls.pop(0))
    monkeypatch.setattr(runner, "diagnose_failure",
                        lambda *a, **k: DiagnosticResult(attribution="agent", consignes="x", reason="r"))
    out = runner.run_with_recovery(_task(), _ctx())
    assert out.status == "qa_failed"
    assert out.attribution == "agent"
    assert out.consignes_tried is True


def test_route_evaluator_reeval_ok_returns_output(monkeypatch):
    monkeypatch.setattr(runner, "run_task", lambda *a, **k: _qa_fail())
    monkeypatch.setattr(runner, "diagnose_failure",
                        lambda *a, **k: DiagnosticResult(attribution="evaluator", consignes=None, reason="r"))
    good_qa = QAResult(task_id="t", agent_id="a", success=True, score=0.9, reason="ok", criteria_results={})
    monkeypatch.setattr(runner, "AdaptiveSpecEvaluator",
                        lambda client: SimpleNamespace(evaluate=lambda task, output: good_qa))
    out = runner.run_with_recovery(_task(), _ctx())
    assert isinstance(out, Output)
    assert out.content == "bad"   # l'output original passe avec le nouvel evaluator


def test_route_evaluator_reeval_ko_then_agent_retry_ok(monkeypatch):
    calls = [_qa_fail(), _output("recovered")]
    monkeypatch.setattr(runner, "run_task", lambda *a, **k: calls.pop(0))
    monkeypatch.setattr(runner, "diagnose_failure",
                        lambda *a, **k: DiagnosticResult(attribution="evaluator", consignes="clarify", reason="r"))
    bad_qa = QAResult(task_id="t", agent_id="a", success=False, score=0.1, reason="still bad", criteria_results={})
    monkeypatch.setattr(runner, "AdaptiveSpecEvaluator",
                        lambda client: SimpleNamespace(evaluate=lambda task, output: bad_qa))
    out = runner.run_with_recovery(_task(), _ctx())
    assert isinstance(out, Output)
    assert out.content == "recovered"


def test_route_evaluator_reeval_ko_then_agent_retry_ko(monkeypatch):
    calls = [_qa_fail(), _qa_fail()]
    monkeypatch.setattr(runner, "run_task", lambda *a, **k: calls.pop(0))
    monkeypatch.setattr(runner, "diagnose_failure",
                        lambda *a, **k: DiagnosticResult(attribution="evaluator", consignes="clarify", reason="r"))
    bad_qa = QAResult(task_id="t", agent_id="a", success=False, score=0.1, reason="bad", criteria_results={})
    monkeypatch.setattr(runner, "AdaptiveSpecEvaluator",
                        lambda client: SimpleNamespace(evaluate=lambda task, output: bad_qa))
    out = runner.run_with_recovery(_task(), _ctx())
    assert out.status == "qa_failed"
    assert out.attribution == "evaluator"
    assert out.consignes_tried is True


def test_route_unattributed_no_retry(monkeypatch):
    monkeypatch.setattr(runner, "run_task", lambda *a, **k: _qa_fail())
    monkeypatch.setattr(runner, "diagnose_failure",
                        lambda *a, **k: DiagnosticResult(attribution="unattributed", reason="r"))
    out = runner.run_with_recovery(_task(), _ctx())
    assert out.status == "qa_failed"
    assert out.attribution == "unattributed"
    assert out.consignes_tried is False


def test_route_diagnostic_none_treated_as_unattributed(monkeypatch):
    monkeypatch.setattr(runner, "run_task", lambda *a, **k: _qa_fail())
    monkeypatch.setattr(runner, "diagnose_failure", lambda *a, **k: None)
    out = runner.run_with_recovery(_task(), _ctx())
    assert out.status == "qa_failed"
    assert out.attribution == "unattributed"
