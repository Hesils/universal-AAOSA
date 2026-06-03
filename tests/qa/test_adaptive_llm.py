from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from aaosa.qa.adaptive import (
    _LLMCriterion,
    _LLMEvaluatorSpec,
    _LLMJudge,
    build_adaptive_spec,
    build_llm_spec,
)
from aaosa.qa.spec import EvaluatorSpec
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
        spec = _LLMEvaluatorSpec(
            criteria=[
                _LLMCriterion(name="non_empty"),
                _LLMCriterion(name="min_length", min_chars=100, weight=1.0),
            ],
            success_threshold=0.8,
        )
        client = _FakeParseClient(spec)
        result = build_llm_spec(make_task(), client)
        assert isinstance(result, EvaluatorSpec)
        assert result.success_threshold == 0.8
        names = {c.name for c in result.criteria}
        assert {"non_empty", "min_length"} <= names

    def test_response_format_is_closed_schema(self):
        # Garde anti-régression : on ne doit JAMAIS repasser EvaluatorSpec (dict ouvert)
        # en response_format — c'est ce qui faisait échouer le structured output.
        client = _FakeParseClient(_LLMEvaluatorSpec(criteria=[_LLMCriterion(name="non_empty")]))
        build_llm_spec(make_task(), client)
        assert client.captured_kwargs["response_format"] is _LLMEvaluatorSpec

    def test_min_chars_converted_to_params(self):
        spec = _LLMEvaluatorSpec(criteria=[_LLMCriterion(name="min_length", min_chars=120)])
        result = build_llm_spec(make_task(), _FakeParseClient(spec))
        ml = next(c for c in result.criteria if c.name == "min_length")
        assert ml.params == {"min_chars": 120}

    def test_judge_converted(self):
        spec = _LLMEvaluatorSpec(
            criteria=[_LLMCriterion(name="non_empty")],
            judge=_LLMJudge(mode="rubric", rubric=["correctness", "completeness"]),
        )
        result = build_llm_spec(make_task(), _FakeParseClient(spec))
        assert result.judge is not None
        assert result.judge.rubric == ["correctness", "completeness"]
        assert result.judge.weight == 0.3

    def test_always_has_non_empty_gate(self):
        # LLM omits non_empty entirely — invariant must re-add it as a gate.
        spec = _LLMEvaluatorSpec(criteria=[_LLMCriterion(name="min_length", min_chars=50)])
        client = _FakeParseClient(spec)
        result = build_llm_spec(make_task(), client)
        gates = [c for c in result.criteria if c.name == "non_empty" and c.gate]
        assert len(gates) == 1

    def test_injects_into_spec_evaluator(self):
        spec = _LLMEvaluatorSpec(criteria=[_LLMCriterion(name="non_empty")])
        client = _FakeParseClient(spec)
        result = build_llm_spec(make_task(), client)
        # judge is None -> SpecEvaluator accepts client=None without raising
        SpecEvaluator(result, client=None)

    def test_fallback_on_exception(self):
        task = make_task()
        result = build_llm_spec(task, _RaisingClient())
        assert result == build_adaptive_spec(task)

    def test_filters_unknown_criteria(self):
        spec = _LLMEvaluatorSpec(
            criteria=[
                _LLMCriterion(name="non_empty"),
                _LLMCriterion(name="hallucinated_criterion", weight=2.0),
                _LLMCriterion(name="min_length", min_chars=50),
            ],
        )
        client = _FakeParseClient(spec)
        result = build_llm_spec(make_task(), client)
        names = {c.name for c in result.criteria}
        assert "hallucinated_criterion" not in names
        assert {"non_empty", "min_length"} <= names

    def test_filters_all_unknown_falls_back(self):
        task = make_task()
        spec = _LLMEvaluatorSpec(
            criteria=[
                _LLMCriterion(name="totally_made_up"),
                _LLMCriterion(name="also_fake"),
            ],
        )
        client = _FakeParseClient(spec)
        result = build_llm_spec(task, client)
        assert result == build_adaptive_spec(task)

    def test_llm_check_preserved_with_description(self):
        spec = _LLMEvaluatorSpec(
            criteria=[
                _LLMCriterion(name="non_empty"),
                _LLMCriterion(name="llm_check", description="must include code examples", weight=1.5),
            ],
        )
        client = _FakeParseClient(spec)
        result = build_llm_spec(make_task(), client)
        llm = next((c for c in result.criteria if c.name == "llm_check"), None)
        assert llm is not None
        assert llm.params == {"description": "must include code examples"}
        assert llm.weight == 1.5

    def test_llm_criterion_rejects_gate_field(self):
        # Le LLM ne peut plus déclarer de gate : seul non_empty en est un (invariant V2b).
        with pytest.raises(ValidationError):
            _LLMCriterion(name="min_length", gate=True)

    def test_llm_judge_rejects_weight_field(self):
        # Le LLM ne contrôle plus le poids du judge (jamais signal primaire, V2b).
        with pytest.raises(ValidationError):
            _LLMJudge(rubric=["correctness"], weight=1.0)

    def test_judge_weight_always_03(self):
        spec = _LLMEvaluatorSpec(
            criteria=[_LLMCriterion(name="non_empty")],
            judge=_LLMJudge(mode="rubric", rubric=["correctness"]),
        )
        result = build_llm_spec(make_task(), _FakeParseClient(spec))
        assert result.judge is not None
        assert result.judge.weight == 0.3

    def test_only_non_empty_is_gate(self):
        # Même si le LLM propose non_empty + min_length, le seul gate de sortie
        # doit être non_empty (min_length reste scoré, gradué).
        spec = _LLMEvaluatorSpec(
            criteria=[
                _LLMCriterion(name="non_empty"),
                _LLMCriterion(name="min_length", min_chars=300),
            ],
        )
        result = build_llm_spec(make_task(), _FakeParseClient(spec))
        gated = [c.name for c in result.criteria if c.gate]
        assert gated == ["non_empty"]
