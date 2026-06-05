from aaosa.qa.diagnostic import FailureContext
from aaosa.qa.protocol import QAResult
from aaosa.runtime.divider import TaskDivider
from aaosa.schemas.output import LLMMetadata, Output
from aaosa.schemas.task import Task


class TestTaskDividerPrompt:
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
