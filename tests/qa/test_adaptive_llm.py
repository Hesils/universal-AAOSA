from types import SimpleNamespace

import pytest

from aaosa.qa.adaptive import build_adaptive_spec, build_llm_spec
from aaosa.qa.spec import CriterionSpec, EvaluatorSpec, JudgeSpec
from aaosa.qa.spec_evaluator import SpecEvaluator
from aaosa.schemas.task import Task


def make_task(required_tags=None, description="Build a login form") -> Task:
    return Task(description=description, required_tags=required_tags or {"frontend": 80})


class _FakeParseClient:
    """Mocks client.beta.chat.completions.parse -> a pre-built EvaluatorSpec."""

    def __init__(self, parsed):
        self._parsed = parsed
        self.captured_kwargs = None
        self.beta = self
        self.chat = self
        self.completions = self

    def parse(self, **kwargs):
        self.captured_kwargs = kwargs
        message = SimpleNamespace(parsed=self._parsed)
        choice = SimpleNamespace(message=message)
        return SimpleNamespace(choices=[choice])


class _RaisingClient:
    def __init__(self):
        self.beta = self
        self.chat = self
        self.completions = self

    def parse(self, **kwargs):
        raise RuntimeError("LLM unavailable")


class TestBuildLLMSpec:
    def test_returns_evaluator_spec(self):
        spec = EvaluatorSpec(
            criteria=[
                CriterionSpec(name="non_empty", gate=True),
                CriterionSpec(name="min_length", params={"min_chars": 100}, weight=1.0),
            ],
            success_threshold=0.8,
        )
        client = _FakeParseClient(spec)
        result = build_llm_spec(make_task(), client)
        assert isinstance(result, EvaluatorSpec)
        assert result.success_threshold == 0.8
        names = {c.name for c in result.criteria}
        assert {"non_empty", "min_length"} <= names

    def test_always_has_non_empty_gate(self):
        # LLM omits non_empty entirely — invariant must re-add it as a gate.
        spec = EvaluatorSpec(
            criteria=[CriterionSpec(name="min_length", params={"min_chars": 50})],
        )
        client = _FakeParseClient(spec)
        result = build_llm_spec(make_task(), client)
        gates = [c for c in result.criteria if c.name == "non_empty" and c.gate]
        assert len(gates) == 1

    def test_injects_into_spec_evaluator(self):
        spec = EvaluatorSpec(
            criteria=[CriterionSpec(name="non_empty", gate=True)],
        )
        client = _FakeParseClient(spec)
        result = build_llm_spec(make_task(), client)
        # judge is None -> SpecEvaluator accepts client=None without raising
        SpecEvaluator(result, client=None)

    def test_fallback_on_exception(self):
        task = make_task()
        result = build_llm_spec(task, _RaisingClient())
        assert result == build_adaptive_spec(task)

    def test_filters_unknown_criteria(self):
        spec = EvaluatorSpec(
            criteria=[
                CriterionSpec(name="non_empty", gate=True),
                CriterionSpec(name="hallucinated_criterion", weight=2.0),
                CriterionSpec(name="min_length", params={"min_chars": 50}),
            ],
        )
        client = _FakeParseClient(spec)
        result = build_llm_spec(make_task(), client)
        names = {c.name for c in result.criteria}
        assert "hallucinated_criterion" not in names
        assert {"non_empty", "min_length"} <= names

    def test_filters_all_unknown_falls_back(self):
        task = make_task()
        spec = EvaluatorSpec(
            criteria=[
                CriterionSpec(name="totally_made_up"),
                CriterionSpec(name="also_fake"),
            ],
        )
        client = _FakeParseClient(spec)
        result = build_llm_spec(task, client)
        assert result == build_adaptive_spec(task)

    def test_llm_check_preserved(self):
        spec = EvaluatorSpec(
            criteria=[
                CriterionSpec(name="non_empty", gate=True),
                CriterionSpec(
                    name="llm_check",
                    params={"description": "must include code examples"},
                    weight=1.5,
                ),
            ],
        )
        client = _FakeParseClient(spec)
        result = build_llm_spec(make_task(), client)
        names = {c.name for c in result.criteria}
        assert "llm_check" in names
