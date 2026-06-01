import json
from types import SimpleNamespace

from aaosa.qa.spec import CriterionSpec, EvaluatorSpec
from aaosa.qa.test_set import TestCase, TestSet
from aaosa.qa.triage import TriageResult, triage_case, triage_unattributed
from aaosa.schemas.output import LLMMetadata, Output
from aaosa.schemas.task import Task


def make_spec() -> EvaluatorSpec:
    return EvaluatorSpec(criteria=[
        CriterionSpec(name="non_empty", gate=True),
        CriterionSpec(name="min_length", params={"min_chars": 50}, weight=1.0),
    ])


def make_task(description="do the thing") -> Task:
    return Task(description=description, required_tags={"python": 60})


def make_output(content="bad output") -> Output:
    return Output(
        task_id="t-1", agent_id="a-1", content=content,
        llm_metadata=LLMMetadata(model_name="m", tokens_in=1, tokens_out=1, latency_ms=1.0),
    )


def make_case(attribution="unattributed", description="do the thing") -> TestCase:
    return TestCase(
        task=make_task(description),
        evaluator_spec=make_spec(),
        reference=None,
        origin="runtime_failure",
        wrong_output=make_output(),
        role="fix_target",
        attribution=attribution,
    )


def _parse_client(attribution="agent", justification="because"):
    """Mock client whose beta.chat.completions.parse returns a TriageResult."""
    result = TriageResult(attribution=attribution, justification=justification)
    parsed = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(parsed=result))])
    return SimpleNamespace(
        beta=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=lambda **kw: parsed)))
    )


def _json_fallback_client(attribution="task_spec", justification="ambiguous"):
    """Mock client: structured parse raises, raw create returns JSON."""
    def parse(**kw):
        raise RuntimeError("structured output unavailable")

    def create(**kw):
        payload = json.dumps({"attribution": attribution, "justification": justification})
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


class TestTriageResult:
    def test_triage_result_valid(self):
        tr = TriageResult(attribution="agent", justification="output is poor")
        roundtrip = TriageResult.model_validate_json(tr.model_dump_json())
        assert roundtrip.attribution == "agent"
        assert roundtrip.justification == "output is poor"


class TestTriageCase:
    def test_triage_case_returns_agent(self):
        result = triage_case(make_case(), _parse_client("agent"))
        assert result is not None
        assert result.attribution == "agent"

    def test_triage_case_returns_task_spec(self):
        result = triage_case(make_case(), _parse_client("task_spec"))
        assert result.attribution == "task_spec"

    def test_triage_case_returns_evaluator(self):
        result = triage_case(make_case(), _parse_client("evaluator"))
        assert result.attribution == "evaluator"

    def test_triage_case_json_fallback(self):
        result = triage_case(make_case(), _json_fallback_client("task_spec"))
        assert result is not None
        assert result.attribution == "task_spec"

    def test_triage_case_llm_failure_returns_none(self):
        assert triage_case(make_case(), _exploding_client()) is None


class TestTriageUnattributed:
    def test_triage_unattributed_attributes_cases(self):
        ts = TestSet(cases=[
            make_case("unattributed", "first"),
            make_case("unattributed", "second"),
            make_case("agent", "already"),
        ])
        result = triage_unattributed(ts, _parse_client("task_spec"))
        assert result.cases[0].attribution == "task_spec"
        assert result.cases[1].attribution == "task_spec"
        assert result.cases[2].attribution == "agent"  # unchanged

    def test_triage_unattributed_skips_already_attributed(self):
        ts = TestSet(cases=[
            make_case("agent"),
            make_case("task_spec"),
            make_case("evaluator"),
        ])
        calls = {"n": 0}

        def parse(**kw):
            calls["n"] += 1
            raise AssertionError("LLM should not be called for attributed cases")

        client = SimpleNamespace(
            beta=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=parse)))
        )
        result = triage_unattributed(ts, client)
        assert calls["n"] == 0
        assert [c.attribution for c in result.cases] == ["agent", "task_spec", "evaluator"]

    def test_triage_unattributed_keeps_unattributed_on_failure(self):
        ts = TestSet(cases=[make_case("unattributed")])
        result = triage_unattributed(ts, _exploding_client())
        assert result.cases[0].attribution == "unattributed"

    def test_triage_unattributed_does_not_mutate_input(self):
        ts = TestSet(cases=[make_case("unattributed")])
        triage_unattributed(ts, _parse_client("agent"))
        assert ts.cases[0].attribution == "unattributed"
