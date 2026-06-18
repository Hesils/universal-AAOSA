from types import SimpleNamespace

import aaosa.runtime.runner as runner
from aaosa.qa.diagnostic import DiagnosticResult
from aaosa.qa.protocol import QAFailure, QAResult
from aaosa.runtime.context import RunContext
from aaosa.runtime.divider import DivisionResult, SubTaskSpec
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
        agents=[_StubAgentRoster()], provider=SimpleNamespace(), divider=SimpleNamespace(),
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
                        lambda client, failure_context=None, model=None: SimpleNamespace(evaluate=lambda task, output: good_qa))
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
                        lambda client, failure_context=None, model=None: SimpleNamespace(evaluate=lambda task, output: bad_qa))
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
                        lambda client, failure_context=None, model=None: SimpleNamespace(evaluate=lambda task, output: bad_qa))
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


# ---------------------------------------------------------------------------
# Route task_spec (D3) — récursion via D1 + terminaison
# ---------------------------------------------------------------------------

class _DividerStub:
    def __init__(self, division):
        self.division = division
        self.calls = []

    def divide(self, task, provider, chained_context=None, failure_context=None, cycle_context=None, model=None):
        self.calls.append(failure_context)
        return self.division


class _AggStub:
    def aggregate(self, task, sinks, provider, tracer=None, model=None):
        return Output(task_id=task.id, agent_id="aggregator", content="aggregated",
                      llm_metadata=LLMMetadata(model_name="m", tokens_in=1, tokens_out=1, latency_ms=1.0))


class _TaggerStub:
    def tag(self, description, agents, provider, model=None):
        return ["python"]


def test_route_task_spec_divides_with_failure_context(monkeypatch):
    # parent run_task → qa_fail ; diagnostic task_spec ; division en 2 sous-tâches
    # indépendantes qui réussissent → 2 sinks → agrégation.
    division = DivisionResult(sub_tasks=[
        SubTaskSpec(description="clarified part A"),
        SubTaskSpec(description="clarified part B"),
    ])
    divider = _DividerStub(division)

    def run_task_side_effect(task, agents, provider, tracer, evaluator, provider_registry=None):
        if task.description == "do x":
            return _qa_fail()                      # parent échoue
        return _output(f"ok:{task.description}")   # sous-tâches réussissent

    monkeypatch.setattr(runner, "run_task", run_task_side_effect)
    monkeypatch.setattr(runner, "diagnose_failure",
                        lambda *a, **k: DiagnosticResult(attribution="task_spec", reason="ambiguë"))

    ctx = RunContext(
        agents=[_StubAgentRoster()], provider=SimpleNamespace(), divider=divider,
        aggregator=_AggStub(), tagger=_TaggerStub(), tracer=None, evaluator=None,
    )
    out = runner.run_with_recovery(_task(), ctx)

    assert isinstance(out, Output)
    assert out.content == "aggregated"
    # le divider a bien reçu un failure_context (pas None)
    assert divider.calls and divider.calls[0] is not None
    assert divider.calls[0].diagnostic_reason == "ambiguë"


def test_route_task_spec_atomic_returns_qa_failed(monkeypatch):
    # divider juge la tâche atomique → pas de division possible → qa_failed(task_spec)
    divider = _DividerStub(DivisionResult(is_atomic=True))
    monkeypatch.setattr(runner, "run_task", lambda *a, **k: _qa_fail())
    monkeypatch.setattr(runner, "diagnose_failure",
                        lambda *a, **k: DiagnosticResult(attribution="task_spec", reason="r"))
    ctx = RunContext(
        agents=[_StubAgentRoster()], provider=SimpleNamespace(), divider=divider,
        aggregator=_AggStub(), tagger=_TaggerStub(), tracer=None, evaluator=None,
    )
    out = runner.run_with_recovery(_task(), ctx)
    assert out.status == "qa_failed"
    assert out.attribution == "task_spec"


def test_route_task_spec_terminates_at_max_depth(monkeypatch):
    # à depth >= MAX_RECOVERY_DEPTH, _divide_and_recover renvoie le fallback sans diviser
    divider = _DividerStub(DivisionResult(sub_tasks=[SubTaskSpec(description="sub")]))
    monkeypatch.setattr(runner, "run_task", lambda *a, **k: _qa_fail())
    monkeypatch.setattr(runner, "diagnose_failure",
                        lambda *a, **k: DiagnosticResult(attribution="task_spec", reason="r"))
    ctx = RunContext(
        agents=[_StubAgentRoster()], provider=SimpleNamespace(), divider=divider,
        aggregator=_AggStub(), tagger=_TaggerStub(), tracer=None, evaluator=None,
    )
    out = runner.run_with_recovery(_task(), ctx, depth=runner.MAX_RECOVERY_DEPTH)
    assert out.status == "qa_failed"
    assert out.attribution == "task_spec"
    assert divider.calls == []   # jamais divisé


def test_route_evaluator_passes_failure_context(monkeypatch):
    monkeypatch.setattr(runner, "run_task", lambda *a, **k: _qa_fail())
    monkeypatch.setattr(runner, "diagnose_failure",
                        lambda *a, **k: DiagnosticResult(
                            attribution="evaluator", consignes=None, reason="critères trop stricts"))
    captured = {}
    good_qa = QAResult(task_id="t", agent_id="a", success=True, score=0.9,
                       reason="ok", criteria_results={})

    def fake_evaluator(client, failure_context=None, model=None):
        captured["fc"] = failure_context
        return SimpleNamespace(evaluate=lambda task, output: good_qa)

    monkeypatch.setattr(runner, "AdaptiveSpecEvaluator", fake_evaluator)
    out = runner.run_with_recovery(_task(), _ctx())
    assert isinstance(out, Output)
    fc = captured["fc"]
    assert fc is not None
    assert fc.diagnostic_reason == "critères trop stricts"
    assert fc.failed_output.content == "bad"        # output raté du _qa_fail()
    assert fc.qa_result.score == 0.2
