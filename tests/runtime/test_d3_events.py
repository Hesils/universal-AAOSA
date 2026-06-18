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
        agents=[_StubAgentRoster()], provider=SimpleNamespace(), divider=SimpleNamespace(),
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
        def divide(self, task, provider, chained_context=None, failure_context=None, cycle_context=None, model=None):
            from aaosa.runtime.divider import DivisionResult
            return DivisionResult(is_atomic=True)

    tracer = Tracer("s")
    ctx = RunContext(agents=[_StubAgentRoster()], provider=SimpleNamespace(), divider=_AtomicDivider(),
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
    ctx = RunContext(agents=[_StubAgentRoster()], provider=SimpleNamespace(), divider=SimpleNamespace(),
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
                        lambda client, failure_context=None, model=None: SimpleNamespace(evaluate=lambda task, output: good_qa))
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
                        lambda client, failure_context=None, model=None: SimpleNamespace(evaluate=lambda task, output: bad_qa))
    tracer = Tracer("s")
    out = runner.run_with_recovery(_task(), _ctx(tracer))
    assert isinstance(out, Output) and out.content == "recovered"
    qa_events = [e for e in tracer.events if isinstance(e, QAEvaluatedEvent)]
    assert len(qa_events) == 1 and qa_events[0].success is False
