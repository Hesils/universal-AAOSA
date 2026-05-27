import pytest

from aaosa.qa.protocol import QAEvaluator, QAResult
from aaosa.qa.rule_based import BasicRuleEvaluator
from aaosa.schemas.output import LLMMetadata, Output
from aaosa.schemas.task import Task


def make_task(required_tags: dict[str, int]) -> Task:
    return Task(description="Test task", required_tags=required_tags)


def make_output(task: Task, content: str) -> Output:
    return Output(
        task_id=task.id,
        agent_id="agent-1",
        content=content,
        llm_metadata=LLMMetadata(
            model_name="gpt-4o-mini",
            tokens_in=10, tokens_out=5, latency_ms=100.0,
        ),
    )


class TestBasicRuleEvaluatorProtocol:
    def test_satisfies_qa_evaluator_protocol(self):
        evaluator = BasicRuleEvaluator()
        assert isinstance(evaluator, QAEvaluator)

    def test_evaluate_returns_qa_result(self):
        evaluator = BasicRuleEvaluator()
        task = make_task({"python": 50})
        output = make_output(task, "A" * 60 + " python related content")
        result = evaluator.evaluate(task, output)
        assert isinstance(result, QAResult)


class TestCriteriaNonEmpty:
    def test_empty_content_fails(self):
        evaluator = BasicRuleEvaluator()
        task = make_task({"python": 50})
        output = make_output(task, "")
        result = evaluator.evaluate(task, output)
        assert result.success is False
        assert result.criteria_results["non_empty"] is False

    def test_non_empty_content_passes(self):
        evaluator = BasicRuleEvaluator()
        task = make_task({"python": 50})
        output = make_output(task, "A" * 60 + " python")
        result = evaluator.evaluate(task, output)
        assert result.criteria_results["non_empty"] is True


class TestCriteriaMinLength:
    def test_short_content_fails(self):
        evaluator = BasicRuleEvaluator()
        task = make_task({"python": 50})
        output = make_output(task, "Too short python")
        result = evaluator.evaluate(task, output)
        assert result.success is False
        assert result.criteria_results["min_length"] is False

    def test_exactly_50_chars_passes(self):
        evaluator = BasicRuleEvaluator()
        task = make_task({"python": 50})
        content = "python " + "x" * 43  # 50 chars total
        output = make_output(task, content)
        result = evaluator.evaluate(task, output)
        assert result.criteria_results["min_length"] is True

    def test_49_chars_fails(self):
        evaluator = BasicRuleEvaluator()
        task = make_task({"python": 50})
        content = "python " + "x" * 42  # 49 chars
        output = make_output(task, content)
        result = evaluator.evaluate(task, output)
        assert result.criteria_results["min_length"] is False


class TestCriteriaReferencesTags:
    def test_content_references_all_tags(self):
        evaluator = BasicRuleEvaluator()
        task = make_task({"python": 50, "backend": 40})
        content = "This python backend solution is comprehensive and well-designed for the task"
        output = make_output(task, content)
        result = evaluator.evaluate(task, output)
        assert result.criteria_results["references_tags"] is True

    def test_content_missing_tag(self):
        evaluator = BasicRuleEvaluator()
        task = make_task({"python": 50, "backend": 40})
        content = "This python solution is comprehensive and well-designed for the task at hand"
        output = make_output(task, content)
        result = evaluator.evaluate(task, output)
        assert result.criteria_results["references_tags"] is False

    def test_case_insensitive_tag_matching(self):
        evaluator = BasicRuleEvaluator()
        task = make_task({"Python": 50})
        content = "This PYTHON solution is comprehensive and thorough for production use"
        output = make_output(task, content)
        result = evaluator.evaluate(task, output)
        assert result.criteria_results["references_tags"] is True


class TestScoreAndSuccess:
    def test_all_criteria_pass_score_1(self):
        evaluator = BasicRuleEvaluator()
        task = make_task({"python": 50})
        content = "This python solution covers everything needed for the implementation task"
        output = make_output(task, content)
        result = evaluator.evaluate(task, output)
        assert result.success is True
        assert result.score == 1.0

    def test_all_criteria_fail_score_0(self):
        evaluator = BasicRuleEvaluator()
        task = make_task({"python": 50})
        output = make_output(task, "")
        result = evaluator.evaluate(task, output)
        assert result.success is False
        assert result.score == 0.0

    def test_partial_criteria_score_between_0_and_1(self):
        evaluator = BasicRuleEvaluator()
        task = make_task({"python": 50})
        # non_empty: True, min_length: False, references_tags: True
        content = "python is great"  # 15 chars < 50
        output = make_output(task, content)
        result = evaluator.evaluate(task, output)
        assert result.success is False
        passed = sum(1 for v in result.criteria_results.values() if v)
        total = len(result.criteria_results)
        assert result.score == pytest.approx(passed / total)

    def test_success_requires_all_criteria(self):
        evaluator = BasicRuleEvaluator()
        task = make_task({"python": 50})
        content = "python " + "x" * 50
        output = make_output(task, content)
        result = evaluator.evaluate(task, output)
        assert result.success is True
        assert all(result.criteria_results.values())

    def test_result_ids_match(self):
        evaluator = BasicRuleEvaluator()
        task = make_task({"python": 50})
        output = make_output(task, "python " + "x" * 50)
        result = evaluator.evaluate(task, output)
        assert result.task_id == task.id
        assert result.agent_id == output.agent_id
