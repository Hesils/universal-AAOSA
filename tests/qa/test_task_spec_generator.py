from unittest.mock import MagicMock

from aaosa.qa.spec import CriterionSpec, EvaluatorSpec
from aaosa.qa.task_spec_generator import (
    TaskSpecFix,
    fix_task_spec,
    fix_task_spec_cases,
)
from aaosa.qa.test_set import TestCase, TestSet
from aaosa.runtime.providers import LLMProvider
from aaosa.schemas.output import LLMMetadata, Output
from aaosa.schemas.task import Task


def make_spec() -> EvaluatorSpec:
    return EvaluatorSpec(criteria=[
        CriterionSpec(name="non_empty", gate=True),
        CriterionSpec(name="min_length", params={"min_chars": 50}, weight=1.0),
    ])


def make_output(content="bad output") -> Output:
    return Output(
        task_id="t-1", agent_id="a-1", content=content,
        llm_metadata=LLMMetadata(model_name="m", tokens_in=1, tokens_out=1, latency_ms=1.0),
    )


def make_case(attribution="task_spec", description="vague task") -> TestCase:
    return TestCase(
        task=Task(description=description, required_tags={"python": 60}),
        evaluator_spec=make_spec(),
        reference=None,
        origin="runtime_failure",
        wrong_output=make_output(),
        role="fix_target",
        attribution=attribution,
    )


class TestTaskSpecFix:
    def test_task_spec_fix_valid(self):
        fix = TaskSpecFix(corrected_description="clear desc", justification="was vague")
        roundtrip = TaskSpecFix.model_validate_json(fix.model_dump_json())
        assert roundtrip.corrected_description == "clear desc"
        assert roundtrip.justification == "was vague"


class TestFixTaskSpec:
    def test_fix_task_spec_corrects_description(self):
        provider = MagicMock(spec=LLMProvider)
        provider.parse.return_value = TaskSpecFix(
            corrected_description="Sharp, specific task.", justification="was ambiguous"
        )
        case = make_case(description="vague task")
        fixed = fix_task_spec(case, provider)
        assert fixed is not None
        assert fixed.task.description == "Sharp, specific task."

    def test_fix_task_spec_resets_attribution(self):
        provider = MagicMock(spec=LLMProvider)
        provider.parse.return_value = TaskSpecFix(
            corrected_description="A clear, specific task description.", justification="was ambiguous"
        )
        fixed = fix_task_spec(make_case(), provider)
        assert fixed.attribution == "unattributed"

    def test_fix_task_spec_preserves_task_id(self):
        provider = MagicMock(spec=LLMProvider)
        provider.parse.return_value = TaskSpecFix(
            corrected_description="A clear, specific task description.", justification="was ambiguous"
        )
        case = make_case()
        fixed = fix_task_spec(case, provider)
        assert fixed.task.id == case.task.id

    def test_fix_task_spec_preserves_role_and_output(self):
        provider = MagicMock(spec=LLMProvider)
        provider.parse.return_value = TaskSpecFix(
            corrected_description="A clear, specific task description.", justification="was ambiguous"
        )
        case = make_case()
        fixed = fix_task_spec(case, provider)
        assert fixed.role == "fix_target"
        assert fixed.wrong_output == case.wrong_output

    def test_fix_task_spec_json_fallback(self):
        # After migration: no more dual-block; provider.parse returning result is sufficient.
        provider = MagicMock(spec=LLMProvider)
        provider.parse.return_value = TaskSpecFix(
            corrected_description="From JSON.", justification="fixed"
        )
        fixed = fix_task_spec(make_case(), provider)
        assert fixed is not None
        assert fixed.task.description == "From JSON."

    def test_fix_task_spec_llm_failure_returns_none(self):
        provider = MagicMock(spec=LLMProvider)
        provider.parse.return_value = None
        assert fix_task_spec(make_case(), provider) is None


class TestFixTaskSpecCases:
    def test_fix_task_spec_cases_fixes_task_spec_only(self):
        ts = TestSet(cases=[
            make_case("task_spec", "broken"),
            make_case("agent", "fine"),
            make_case("evaluator", "strict"),
        ])
        provider = MagicMock(spec=LLMProvider)
        provider.parse.return_value = TaskSpecFix(
            corrected_description="Fixed.", justification="was ambiguous"
        )
        result = fix_task_spec_cases(ts, provider)
        assert result.cases[0].task.description == "Fixed."
        assert result.cases[0].attribution == "unattributed"
        assert result.cases[1].task.description == "fine"
        assert result.cases[1].attribution == "agent"
        assert result.cases[2].attribution == "evaluator"

    def test_fix_task_spec_cases_keeps_task_spec_on_failure(self):
        ts = TestSet(cases=[make_case("task_spec")])
        provider = MagicMock(spec=LLMProvider)
        provider.parse.return_value = None
        result = fix_task_spec_cases(ts, provider)
        assert result.cases[0].attribution == "task_spec"

    def test_fix_task_spec_cases_does_not_mutate_input(self):
        ts = TestSet(cases=[make_case("task_spec", "original")])
        provider = MagicMock(spec=LLMProvider)
        provider.parse.return_value = TaskSpecFix(
            corrected_description="Fixed.", justification="was ambiguous"
        )
        fix_task_spec_cases(ts, provider)
        assert ts.cases[0].task.description == "original"
        assert ts.cases[0].attribution == "task_spec"
