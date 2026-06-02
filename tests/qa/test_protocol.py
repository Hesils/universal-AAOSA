import pytest

from aaosa.qa.protocol import QAResult, QAEvaluator, QAFailure
from aaosa.schemas.task import Task
from aaosa.schemas.output import Output, LLMMetadata


def _make_output(content: str = "ok") -> Output:
    return Output(
        task_id="t1",
        agent_id="a1",
        content=content,
        llm_metadata=LLMMetadata(
            model_name="gpt-4o-mini",
            tokens_in=10,
            tokens_out=5,
            latency_ms=100.0,
        ),
    )


def _make_qa_result(success: bool = True, score: float = 0.8) -> QAResult:
    return QAResult(
        task_id="t1",
        agent_id="a1",
        success=success,
        score=score,
        reason="ok" if success else "fail",
        criteria_results={},
    )


class TestQAResult:
    def test_valid_qa_result(self):
        r = QAResult(
            task_id="t1",
            agent_id="a1",
            success=True,
            score=0.95,
            reason="All criteria met",
            criteria_results={"non_empty": True, "min_length": True},
        )
        assert r.success is True
        assert r.score == 0.95
        assert r.criteria_results == {"non_empty": True, "min_length": True}

    def test_qa_result_failure(self):
        r = QAResult(
            task_id="t1",
            agent_id="a1",
            success=False,
            score=0.3,
            reason="Too short",
            criteria_results={"non_empty": True, "min_length": False},
        )
        assert r.success is False
        assert r.score == 0.3

    def test_qa_result_score_zero(self):
        r = QAResult(
            task_id="t1", agent_id="a1", success=False,
            score=0.0, reason="Empty", criteria_results={},
        )
        assert r.score == 0.0

    def test_qa_result_score_one(self):
        r = QAResult(
            task_id="t1", agent_id="a1", success=True,
            score=1.0, reason="Perfect", criteria_results={"all": True},
        )
        assert r.score == 1.0

    def test_qa_result_empty_criteria(self):
        r = QAResult(
            task_id="t1", agent_id="a1", success=True,
            score=1.0, reason="No criteria", criteria_results={},
        )
        assert r.criteria_results == {}

    def test_qa_result_serialization_roundtrip(self):
        r = QAResult(
            task_id="t1", agent_id="a1", success=True,
            score=0.8, reason="ok", criteria_results={"c1": True},
        )
        data = r.model_dump()
        r2 = QAResult(**data)
        assert r2 == r

    def test_qa_result_json_roundtrip(self):
        r = QAResult(
            task_id="t1", agent_id="a1", success=True,
            score=0.8, reason="ok", criteria_results={"c1": True},
        )
        json_str = r.model_dump_json()
        r2 = QAResult.model_validate_json(json_str)
        assert r2 == r

    def test_qa_result_extra_fields_forbidden(self):
        with pytest.raises(Exception):
            QAResult(
                task_id="t1", agent_id="a1", success=True,
                score=0.8, reason="ok", criteria_results={},
                unknown_field="oops",
            )


class TestQAFailure:
    def test_valid_qa_failure(self):
        output = _make_output("Short")
        qa_result = QAResult(
            task_id="t1", agent_id="a1", success=False,
            score=0.2, reason="Too short",
            criteria_results={"min_length": False},
        )
        f = QAFailure(task_id="t1", agent_id="a1", output=output, qa_result=qa_result)
        assert f.output.content == "Short"
        assert f.qa_result.success is False

    def test_qa_failure_preserves_output(self):
        output = _make_output("Rejected content that should be preserved")
        qa_result = _make_qa_result(success=False, score=0.1)
        f = QAFailure(task_id="t1", agent_id="a1", output=output, qa_result=qa_result)
        assert f.output.content == "Rejected content that should be preserved"

    def test_qa_failure_serialization_roundtrip(self):
        output = _make_output("x")
        qa_result = _make_qa_result(success=False, score=0.0)
        f = QAFailure(task_id="t1", agent_id="a1", output=output, qa_result=qa_result)
        data = f.model_dump()
        f2 = QAFailure(**data)
        assert f2.task_id == f.task_id

    def test_qa_failure_extra_fields_forbidden(self):
        with pytest.raises(Exception):
            QAFailure(
                task_id="t1", agent_id="a1",
                output=None, qa_result=None,
                unknown="oops",
            )


def test_qaresult_spec_used_defaults_none():
    from aaosa.qa.protocol import QAResult
    r = QAResult(
        task_id="t1", agent_id="a1", success=True, score=1.0,
        reason="ok", criteria_results={"non_empty": True},
    )
    assert r.spec_used is None


def test_qaresult_accepts_spec_used():
    from aaosa.qa.protocol import QAResult
    from aaosa.qa.spec import CriterionSpec, EvaluatorSpec
    spec = EvaluatorSpec(criteria=[CriterionSpec(name="non_empty", gate=True)])
    r = QAResult(
        task_id="t1", agent_id="a1", success=True, score=1.0,
        reason="ok", criteria_results={"non_empty": True}, spec_used=spec,
    )
    assert r.spec_used == spec


class TestQAEvaluatorProtocol:
    def test_class_with_evaluate_method_satisfies_protocol(self):
        class FakeEvaluator:
            def evaluate(self, task: Task, output: Output) -> QAResult:
                return QAResult(
                    task_id=task.id, agent_id=output.agent_id,
                    success=True, score=1.0, reason="ok",
                    criteria_results={},
                )

        evaluator = FakeEvaluator()
        assert isinstance(evaluator, QAEvaluator)

    def test_class_without_evaluate_does_not_satisfy(self):
        class NotAnEvaluator:
            pass

        assert not isinstance(NotAnEvaluator(), QAEvaluator)

    def test_protocol_is_runtime_checkable(self):
        from typing import Protocol as TypingProtocol
        assert issubclass(QAEvaluator, TypingProtocol)
