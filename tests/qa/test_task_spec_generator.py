import json
from types import SimpleNamespace

from aaosa.qa.spec import CriterionSpec, EvaluatorSpec
from aaosa.qa.task_spec_generator import (
    TaskSpecFix,
    fix_task_spec,
    fix_task_spec_cases,
)
from aaosa.qa.test_set import TestCase, TestSet
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


def _parse_client(corrected="A clear, specific task description.", justification="was ambiguous"):
    result = TaskSpecFix(corrected_description=corrected, justification=justification)
    parsed = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(parsed=result))])
    return SimpleNamespace(
        beta=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=lambda **kw: parsed)))
    )


def _json_fallback_client(corrected="Corrected via JSON.", justification="fixed"):
    def parse(**kw):
        raise RuntimeError("structured output unavailable")

    def create(**kw):
        payload = json.dumps({"corrected_description": corrected, "justification": justification})
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=payload))])

    return SimpleNamespace(
        beta=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=parse))),
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
    )


def _exploding_client():
    def parse(**kw):
        raise RuntimeError("parse boom")

    def create(**kw):
        raise RuntimeError("create boom")

    return SimpleNamespace(
        beta=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=parse))),
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
    )


class TestTaskSpecFix:
    def test_task_spec_fix_valid(self):
        fix = TaskSpecFix(corrected_description="clear desc", justification="was vague")
        roundtrip = TaskSpecFix.model_validate_json(fix.model_dump_json())
        assert roundtrip.corrected_description == "clear desc"
        assert roundtrip.justification == "was vague"


class TestFixTaskSpec:
    def test_fix_task_spec_corrects_description(self):
        case = make_case(description="vague task")
        fixed = fix_task_spec(case, _parse_client("Sharp, specific task."))
        assert fixed is not None
        assert fixed.task.description == "Sharp, specific task."

    def test_fix_task_spec_resets_attribution(self):
        fixed = fix_task_spec(make_case(), _parse_client())
        assert fixed.attribution == "unattributed"

    def test_fix_task_spec_preserves_task_id(self):
        case = make_case()
        fixed = fix_task_spec(case, _parse_client())
        assert fixed.task.id == case.task.id

    def test_fix_task_spec_preserves_role_and_output(self):
        case = make_case()
        fixed = fix_task_spec(case, _parse_client())
        assert fixed.role == "fix_target"
        assert fixed.wrong_output == case.wrong_output

    def test_fix_task_spec_json_fallback(self):
        fixed = fix_task_spec(make_case(), _json_fallback_client("From JSON."))
        assert fixed is not None
        assert fixed.task.description == "From JSON."

    def test_fix_task_spec_llm_failure_returns_none(self):
        assert fix_task_spec(make_case(), _exploding_client()) is None


class TestFixTaskSpecCases:
    def test_fix_task_spec_cases_fixes_task_spec_only(self):
        ts = TestSet(cases=[
            make_case("task_spec", "broken"),
            make_case("agent", "fine"),
            make_case("evaluator", "strict"),
        ])
        result = fix_task_spec_cases(ts, _parse_client("Fixed."))
        assert result.cases[0].task.description == "Fixed."
        assert result.cases[0].attribution == "unattributed"
        assert result.cases[1].task.description == "fine"
        assert result.cases[1].attribution == "agent"
        assert result.cases[2].attribution == "evaluator"

    def test_fix_task_spec_cases_keeps_task_spec_on_failure(self):
        ts = TestSet(cases=[make_case("task_spec")])
        result = fix_task_spec_cases(ts, _exploding_client())
        assert result.cases[0].attribution == "task_spec"

    def test_fix_task_spec_cases_does_not_mutate_input(self):
        ts = TestSet(cases=[make_case("task_spec", "original")])
        fix_task_spec_cases(ts, _parse_client("Fixed."))
        assert ts.cases[0].task.description == "original"
        assert ts.cases[0].attribution == "task_spec"
