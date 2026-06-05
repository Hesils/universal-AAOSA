import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from aaosa.qa.diagnostic import DiagnosticResult, FailureContext, diagnose_failure
from aaosa.qa.protocol import QAResult
from aaosa.schemas.output import LLMMetadata, Output
from aaosa.schemas.task import Task


def _output(content="bad") -> Output:
    return Output(task_id="t-1", agent_id="a-1", content=content,
                  llm_metadata=LLMMetadata(model_name="m", tokens_in=1, tokens_out=1, latency_ms=1.0))


def _qa_result() -> QAResult:
    return QAResult(task_id="t-1", agent_id="a-1", success=False, score=0.2,
                    reason="too short", criteria_results={"min_length": False})


def _task() -> Task:
    return Task(description="do the thing", required_tags={"python": 60})


def _parse_client(attribution="agent", consignes="be concise", reason="r"):
    result = DiagnosticResult(attribution=attribution, consignes=consignes, reason=reason)
    parsed = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(parsed=result))])
    return SimpleNamespace(
        beta=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=lambda **kw: parsed)))
    )


def _json_fallback_client(attribution="task_spec", reason="ambiguous"):
    def parse(**kw):
        raise RuntimeError("structured output unavailable")

    def create(**kw):
        payload = json.dumps({"attribution": attribution, "consignes": None, "reason": reason})
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=payload))])

    return SimpleNamespace(
        beta=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=parse))),
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
    )


def _exploding_client():
    def boom(**kw):
        raise RuntimeError("boom")
    return SimpleNamespace(
        beta=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=boom))),
        chat=SimpleNamespace(completions=SimpleNamespace(create=boom)),
    )


def test_failure_context_carries_output_and_qa():
    fc = FailureContext(failed_output=_output(), qa_result=_qa_result(),
                        diagnostic_reason="ambiguous spec")
    assert fc.failed_output.content == "bad"
    assert fc.qa_result.success is False
    assert fc.diagnostic_reason == "ambiguous spec"


def test_diagnostic_result_accepts_known_attributions():
    for attr in ("agent", "evaluator", "task_spec", "unattributed"):
        DiagnosticResult(attribution=attr, reason="r")


def test_diagnostic_result_rejects_unknown_attribution():
    with pytest.raises(ValidationError):
        DiagnosticResult(attribution="weird", reason="r")


def test_diagnostic_result_consignes_optional():
    d = DiagnosticResult(attribution="task_spec", reason="r")
    assert d.consignes is None


def test_diagnose_structured_output_returns_result():
    out = diagnose_failure(_task(), _output(), _qa_result(), _parse_client(attribution="agent"))
    assert out.attribution == "agent"
    assert out.consignes == "be concise"


def test_diagnose_json_fallback_when_structured_fails():
    out = diagnose_failure(_task(), _output(), _qa_result(), _json_fallback_client("task_spec"))
    assert out.attribution == "task_spec"
    assert out.consignes is None


def test_diagnose_returns_none_on_unrecoverable_llm_failure():
    out = diagnose_failure(_task(), _output(), _qa_result(), _exploding_client())
    assert out is None
