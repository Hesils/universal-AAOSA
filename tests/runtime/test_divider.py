import pytest
from unittest.mock import MagicMock

from aaosa.qa.diagnostic import FailureContext
from aaosa.qa.protocol import QAResult
from aaosa.runtime.divider import DivisionResult, SubTaskSpec, TaskDivider
from aaosa.runtime.providers import LLMProvider
from aaosa.schemas.output import LLMMetadata, Output
from aaosa.schemas.task import Task


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_task(desc: str = "ship the feature") -> Task:
    return Task(description=desc, required_tags={"python": 50})


def _make_division(atomic: bool = False) -> DivisionResult:
    if atomic:
        return DivisionResult(is_atomic=True)
    return DivisionResult(sub_tasks=[
        SubTaskSpec(description="write tests"),
        SubTaskSpec(description="write code", depends_on_indices=[0]),
    ])


# ---------------------------------------------------------------------------
# Prompt tests (no LLM, pure string-building)
# ---------------------------------------------------------------------------

class TestTaskDividerPrompt:
    def test_prompt_unchanged_without_optional_context(self):
        divider = TaskDivider(system_prompt="sp")
        task = _make_task()
        p = divider._build_divide_prompt(task, None, None)
        assert "ship the feature" in p
        assert "Contexte hérité" not in p
        assert "Échec précédent" not in p

    def test_prompt_includes_chained_context(self):
        divider = TaskDivider(system_prompt="sp")
        task = _make_task()
        ancestor = Task(description="big incident triage", required_tags={"backend": 70})
        p = divider._build_divide_prompt(task, [ancestor], None)
        assert "big incident triage" in p
        assert "Contexte hérité" in p

    def test_prompt_includes_failure_context(self):
        divider = TaskDivider(system_prompt="sp")
        task = _make_task()
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
        task = _make_task()
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


# ---------------------------------------------------------------------------
# LLM call tests — mock provider.parse / provider.complete
# ---------------------------------------------------------------------------

class TestTaskDividerDivide:
    def test_divide_returns_parsed_division(self):
        provider = MagicMock(spec=LLMProvider)
        provider.parse.return_value = _make_division()
        task = _make_task()
        result = TaskDivider(system_prompt="sp").divide(task, provider)
        assert result == provider.parse.return_value

    def test_divide_raises_when_parse_returns_none(self):
        provider = MagicMock(spec=LLMProvider)
        provider.parse.return_value = None
        task = _make_task()
        with pytest.raises(ValueError, match="divider returned no parsed DivisionResult"):
            TaskDivider(system_prompt="sp").divide(task, provider)

    def test_divide_calls_parse_with_correct_schema(self):
        from aaosa.runtime.divider import DivisionResult
        provider = MagicMock(spec=LLMProvider)
        provider.parse.return_value = _make_division(atomic=True)
        task = _make_task()
        TaskDivider(system_prompt="sp").divide(task, provider)
        call_kwargs = provider.parse.call_args.kwargs
        assert call_kwargs["schema"] is DivisionResult
        assert call_kwargs["temperature"] == 0.0

    def test_divide_passes_task_description_in_messages(self):
        provider = MagicMock(spec=LLMProvider)
        provider.parse.return_value = _make_division()
        task = _make_task("deploy to prod")
        TaskDivider(system_prompt="sys").divide(task, provider)
        messages = provider.parse.call_args.kwargs["messages"]
        user_content = next(m["content"] for m in messages if m["role"] == "user")
        assert "deploy to prod" in user_content

    def test_divide_passes_system_prompt_in_messages(self):
        provider = MagicMock(spec=LLMProvider)
        provider.parse.return_value = _make_division()
        task = _make_task()
        TaskDivider(system_prompt="my-system-prompt").divide(task, provider)
        messages = provider.parse.call_args.kwargs["messages"]
        sys_content = next(m["content"] for m in messages if m["role"] == "system")
        assert sys_content == "my-system-prompt"

    def test_divide_relays_model_param_to_parse(self):
        """model='some-model' must be forwarded to provider.parse."""
        provider = MagicMock(spec=LLMProvider)
        provider.parse.return_value = _make_division()
        task = _make_task()
        TaskDivider(system_prompt="sp").divide(task, provider, model="some-model")
        call_kwargs = provider.parse.call_args.kwargs
        assert call_kwargs.get("model") == "some-model"

    def test_divide_model_none_by_default(self):
        """model=None (default) is passed to provider.parse — provider uses its default."""
        provider = MagicMock(spec=LLMProvider)
        provider.parse.return_value = _make_division()
        task = _make_task()
        TaskDivider(system_prompt="sp").divide(task, provider)
        call_kwargs = provider.parse.call_args.kwargs
        assert call_kwargs.get("model") is None
