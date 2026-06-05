from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from aaosa.qa.adaptive import (
    _IMPORTANCE_WEIGHT,
    _LLMCriterion,
    _LLMEvaluatorSpec,
    _LLMJudge,
    _apply_caps,
    build_adaptive_spec,
    build_llm_spec,
)
from aaosa.qa.spec import CriterionSpec, EvaluatorSpec
from aaosa.qa.spec_evaluator import SpecEvaluator
from aaosa.schemas.task import Task


class TestApplyCaps:
    def test_caps_total_scored_to_six(self):
        crit = [
            CriterionSpec(name="min_length", weight=2.0) for _ in range(8)
        ]
        kept = _apply_caps(crit)
        assert len(kept) == 6

    def test_caps_llm_check_to_four(self):
        crit = [CriterionSpec(name="llm_check", params={"description": str(i)}, weight=2.0)
                for i in range(6)]
        kept = _apply_caps(crit)
        assert sum(c.name == "llm_check" for c in kept) == 4

    def test_caps_keep_highest_importance_first(self):
        crit = [
            CriterionSpec(name="min_length", weight=1.0, rationale="mineur"),
            CriterionSpec(name="references_tags", weight=3.0, rationale="critique"),
            CriterionSpec(name="format_check", weight=2.0, rationale="normal"),
        ]
        # cap fictif : on garde tout (3 ≤ 6) mais l'ordre est trié par weight desc
        kept = _apply_caps(crit)
        assert [c.rationale for c in kept] == ["critique", "normal", "mineur"]

    def test_caps_preserve_emission_order_within_importance(self):
        crit = [
            CriterionSpec(name="min_length", weight=2.0, rationale="first"),
            CriterionSpec(name="references_tags", weight=2.0, rationale="second"),
        ]
        kept = _apply_caps(crit)
        assert [c.rationale for c in kept] == ["first", "second"]

    def test_caps_ignore_gates(self):
        crit = [CriterionSpec(name="non_empty", gate=True)] + [
            CriterionSpec(name="min_length", weight=2.0) for _ in range(6)
        ]
        kept = _apply_caps(crit)
        # le gate est conservé en plus des 6 scorés, et placé en tête
        assert kept[0].name == "non_empty" and kept[0].gate is True
        assert sum(not c.gate for c in kept) == 6


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


class TestLLMCriterionSchema:
    def test_importance_maps_to_weight(self):
        for importance, weight in [("critique", 3.0), ("normal", 2.0), ("mineur", 1.0)]:
            c = _LLMCriterion(type="min_length", importance=importance, min_chars=10)
            assert c.to_criterion().weight == weight

    def test_importance_defaults_normal(self):
        c = _LLMCriterion(type="references_tags")
        assert c.to_criterion().weight == _IMPORTANCE_WEIGHT["normal"]

    def test_rationale_carried_to_criterion(self):
        c = _LLMCriterion(type="llm_check", description="d", rationale="pourquoi")
        assert c.to_criterion().rationale == "pourquoi"

    def test_type_becomes_criterion_name(self):
        c = _LLMCriterion(type="format_check", kind="json")
        assert c.to_criterion().name == "format_check"

    def test_params_gated_by_type(self):
        # min_length avec des keywords parasites : seuls les params du type sont copiés
        c = _LLMCriterion(type="min_length", min_chars=80, keywords=["x"], description="y")
        assert c.to_criterion().params == {"min_chars": 80}

    def test_keyword_presence_params(self):
        c = _LLMCriterion(type="keyword_presence", keywords=["a", "b"])
        assert c.to_criterion().params == {"keywords": ["a", "b"]}

    def test_references_tags_has_no_params(self):
        c = _LLMCriterion(type="references_tags", min_chars=10)
        assert c.to_criterion().params == {}

    def test_criterion_rejects_weight_field(self):
        with pytest.raises(ValidationError):
            _LLMCriterion(type="min_length", weight=2.0)

    def test_criterion_rejects_gate_field(self):
        with pytest.raises(ValidationError):
            _LLMCriterion(type="min_length", gate=True)

    def test_criterion_rejects_unknown_type(self):
        with pytest.raises(ValidationError):
            _LLMCriterion(type="totally_made_up")

    def test_evaluator_spec_has_no_threshold_field(self):
        with pytest.raises(ValidationError):
            _LLMEvaluatorSpec(criteria=[], success_threshold=0.9)

    def test_to_spec_builds_evaluator_spec(self):
        llm = _LLMEvaluatorSpec(criteria=[_LLMCriterion(type="min_length", min_chars=50)])
        spec = llm.to_spec()
        assert [c.name for c in spec.criteria] == ["min_length"]
