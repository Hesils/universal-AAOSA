from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from aaosa.qa.diagnostic import DiagnosticResult, FailureContext, diagnose_failure
from aaosa.qa.protocol import QAResult
from aaosa.runtime.providers import LLMProvider
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
    provider = MagicMock(spec=LLMProvider)
    provider.parse.return_value = DiagnosticResult(attribution="agent", consignes="be concise", reason="r")
    out = diagnose_failure(_task(), _output(), _qa_result(), provider)
    assert out.attribution == "agent"
    assert out.consignes == "be concise"


def test_diagnose_json_fallback_when_structured_fails():
    # After migration: no more dual-block. Provider.parse returning a result is enough.
    provider = MagicMock(spec=LLMProvider)
    provider.parse.return_value = DiagnosticResult(attribution="task_spec", consignes=None, reason="ambiguous")
    out = diagnose_failure(_task(), _output(), _qa_result(), provider)
    assert out.attribution == "task_spec"
    assert out.consignes is None


def test_diagnose_returns_none_on_unrecoverable_llm_failure():
    provider = MagicMock(spec=LLMProvider)
    provider.parse.return_value = None
    out = diagnose_failure(_task(), _output(), _qa_result(), provider)
    assert out is None


def test_diagnose_relays_model_to_provider():
    provider = MagicMock(spec=LLMProvider)
    provider.parse.return_value = DiagnosticResult(attribution="agent", reason="r")
    diagnose_failure(_task(), _output(), _qa_result(), provider, model="gpt-4o-mini")
    call_kwargs = provider.parse.call_args.kwargs
    assert call_kwargs.get("model") == "gpt-4o-mini"
