from types import SimpleNamespace

import pytest

from aaosa.qa.diagnostic import FailureContext
from aaosa.qa.protocol import QAResult
from aaosa.runtime.divider import DivisionResult, SubTaskSpec, TaskDivider
from aaosa.schemas.output import LLMMetadata, Output
from aaosa.schemas.task import Task


def _client_returning(division_result):
    parsed = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(parsed=division_result))])
    return SimpleNamespace(
        beta=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=lambda **kw: parsed)))
    )


class TestDivisionResult:
    def test_non_atomic_requires_subtasks(self):
        with pytest.raises(ValueError, match="non-atomic"):
            DivisionResult(is_atomic=False, sub_tasks=[])

    def test_atomic_forbids_subtasks(self):
        with pytest.raises(ValueError, match="atomic"):
            DivisionResult(is_atomic=True, sub_tasks=[SubTaskSpec(description="x")])

    def test_atomic_ok_with_no_subtasks(self):
        d = DivisionResult(is_atomic=True, sub_tasks=[])
        assert d.is_atomic is True

    def test_subtaskspec_has_no_tags(self):
        spec = SubTaskSpec(description="x", depends_on_indices=[0])
        assert not hasattr(spec, "required_tags")


class TestTaskDivider:
    def test_divide_returns_division_result(self):
        from aaosa.schemas.task import Task
        result = DivisionResult(sub_tasks=[
            SubTaskSpec(description="a"),
            SubTaskSpec(description="b", depends_on_indices=[0]),
        ])
        divider = TaskDivider(system_prompt="split")
        out = divider.divide(Task(description="t", required_tags={"python": 30}), _client_returning(result))
        assert isinstance(out, DivisionResult)
        assert [s.description for s in out.sub_tasks] == ["a", "b"]
        assert out.sub_tasks[1].depends_on_indices == [0]

    def test_divide_passes_through_atomic_verdict(self):
        from aaosa.schemas.task import Task
        result = DivisionResult(is_atomic=True, sub_tasks=[])
        divider = TaskDivider(system_prompt="split")
        out = divider.divide(Task(description="t", required_tags={"python": 30}), _client_returning(result))
        assert out.is_atomic is True

    def test_divide_raises_on_none_parsed(self):
        divider = TaskDivider(system_prompt="split")
        with pytest.raises(ValueError, match="no parsed"):
            divider.divide(Task(description="t", required_tags={"python": 30}), _client_returning(None))

    def test_prompt_unchanged_without_optional_context(self):
        divider = TaskDivider(system_prompt="sp")
        task = Task(description="ship the feature", required_tags={"python": 50})
        p = divider._build_divide_prompt(task, None, None)
        assert "ship the feature" in p
        assert "Contexte hérité" not in p
        assert "Échec précédent" not in p

    def test_prompt_includes_chained_context(self):
        divider = TaskDivider(system_prompt="sp")
        task = Task(description="ship the feature", required_tags={"python": 50})
        ancestor = Task(description="big incident triage", required_tags={"backend": 70})
        p = divider._build_divide_prompt(task, [ancestor], None)
        assert "big incident triage" in p
        assert "Contexte hérité" in p

    def test_prompt_includes_failure_context(self):
        divider = TaskDivider(system_prompt="sp")
        task = Task(description="ship the feature", required_tags={"python": 50})
        out = Output(
            task_id="t",
            agent_id="a",
            content="wrong answer",
            llm_metadata=LLMMetadata(model_name="m", tokens_in=1, tokens_out=1, latency_ms=1.0),
        )
        qa = QAResult(task_id="t", agent_id="a", success=False, score=0.1, reason="off-topic", criteria_results={})
        fc = FailureContext(failed_output=out, qa_result=qa, diagnostic_reason="spec ambiguë")
        p = divider._build_divide_prompt(task, None, fc)
        assert "Échec précédent" in p
        assert "spec ambiguë" in p
        assert "wrong answer" in p

    def test_prompt_includes_both_chained_and_failure_context(self):
        divider = TaskDivider(system_prompt="sp")
        task = Task(description="ship the feature", required_tags={"python": 50})
        ancestor = Task(description="big incident triage", required_tags={"backend": 70})
        out = Output(
            task_id="t",
            agent_id="a",
            content="wrong answer",
            llm_metadata=LLMMetadata(model_name="m", tokens_in=1, tokens_out=1, latency_ms=1.0),
        )
        qa = QAResult(task_id="t", agent_id="a", success=False, score=0.1, reason="off-topic", criteria_results={})
        fc = FailureContext(failed_output=out, qa_result=qa, diagnostic_reason="spec ambiguë")
        p = divider._build_divide_prompt(task, [ancestor], fc)
        assert "big incident triage" in p
        assert "Contexte hérité" in p
        assert "Échec précédent" in p
        assert "spec ambiguë" in p
        assert "wrong answer" in p
