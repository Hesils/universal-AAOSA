import pytest
from pydantic import ValidationError

from aaosa.qa.diagnostic import DiagnosticResult, FailureContext
from aaosa.qa.protocol import QAResult
from aaosa.schemas.output import LLMMetadata, Output


def _output(content="bad") -> Output:
    return Output(task_id="t-1", agent_id="a-1", content=content,
                  llm_metadata=LLMMetadata(model_name="m", tokens_in=1, tokens_out=1, latency_ms=1.0))


def _qa_result() -> QAResult:
    return QAResult(task_id="t-1", agent_id="a-1", success=False, score=0.2,
                    reason="too short", criteria_results={"min_length": False})


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
