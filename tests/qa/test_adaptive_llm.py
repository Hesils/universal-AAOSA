from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from aaosa.qa.diagnostic import FailureContext
from aaosa.qa.protocol import QAResult
from aaosa.schemas.output import LLMMetadata, Output
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
    """Mocks provider.client.beta.chat.completions.parse -> a pre-built EvaluatorSpec."""

    def __init__(self, parsed):
        self._parsed = parsed
        self.captured_kwargs = None
        self.beta = self
        self.chat = self
        self.completions = self

    @property
    def client(self):
        return self

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

    @property
    def client(self):
        return self

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


class TestBuildLLMSpecColdStart:
    def test_returns_evaluator_spec(self):
        llm = _LLMEvaluatorSpec(criteria=[_LLMCriterion(type="min_length", min_chars=100)])
        result = build_llm_spec(make_task(), _FakeParseClient(llm))
        assert isinstance(result, EvaluatorSpec)
        assert "min_length" in {c.name for c in result.criteria}

    def test_response_format_is_closed_schema(self):
        client = _FakeParseClient(_LLMEvaluatorSpec(criteria=[]))
        build_llm_spec(make_task(), client)
        assert client.captured_kwargs["response_format"] is _LLMEvaluatorSpec

    def test_always_has_non_empty_gate(self):
        llm = _LLMEvaluatorSpec(criteria=[_LLMCriterion(type="min_length", min_chars=50)])
        result = build_llm_spec(make_task(), _FakeParseClient(llm))
        gates = [c for c in result.criteria if c.name == "non_empty" and c.gate]
        assert len(gates) == 1

    def test_threshold_is_derived_not_from_llm(self):
        # tag expert → 0.8, indépendamment de ce que "voudrait" le LLM
        llm = _LLMEvaluatorSpec(criteria=[_LLMCriterion(type="min_length", min_chars=50)])
        task = make_task(required_tags={"frontend": 90})
        result = build_llm_spec(task, _FakeParseClient(llm))
        assert result.success_threshold == 0.8

    def test_importance_mapped_in_resulting_spec(self):
        llm = _LLMEvaluatorSpec(criteria=[
            _LLMCriterion(type="min_length", importance="critique", min_chars=50),
        ])
        result = build_llm_spec(make_task(), _FakeParseClient(llm))
        ml = next(c for c in result.criteria if c.name == "min_length")
        assert ml.weight == 3.0

    def test_rationale_present_on_generated_criteria(self):
        llm = _LLMEvaluatorSpec(criteria=[
            _LLMCriterion(type="llm_check", description="d", rationale="parce que"),
        ])
        result = build_llm_spec(make_task(), _FakeParseClient(llm))
        llm_c = next(c for c in result.criteria if c.name == "llm_check")
        assert llm_c.rationale == "parce que"

    def test_caps_enforced_end_to_end(self):
        llm = _LLMEvaluatorSpec(criteria=[
            _LLMCriterion(type="llm_check", description=str(i)) for i in range(6)
        ])
        result = build_llm_spec(make_task(), _FakeParseClient(llm))
        assert sum(c.name == "llm_check" for c in result.criteria) == 4

    def test_judge_converted_weight_locked(self):
        llm = _LLMEvaluatorSpec(
            criteria=[_LLMCriterion(type="min_length", min_chars=50)],
            judge=_LLMJudge(mode="rubric", rubric=["correctness"]),
        )
        result = build_llm_spec(make_task(), _FakeParseClient(llm))
        assert result.judge is not None and result.judge.weight == 0.3

    def test_filters_unknown_criteria_kept_known(self):
        llm = _LLMEvaluatorSpec(criteria=[_LLMCriterion(type="references_tags")])
        result = build_llm_spec(make_task(), _FakeParseClient(llm))
        assert "references_tags" in {c.name for c in result.criteria}

    def test_fallback_on_exception(self):
        task = make_task()
        result = build_llm_spec(task, _RaisingClient())
        assert result == build_adaptive_spec(task)

    def test_prompt_lists_types_and_caps(self):
        client = _FakeParseClient(_LLMEvaluatorSpec(criteria=[]))
        build_llm_spec(make_task(), client)
        prompt = client.captured_kwargs["messages"][1]["content"]
        assert "llm_check" in prompt and "min_length" in prompt
        assert "importance" in prompt
        assert "non_empty" in prompt  # consigne de ne pas le déclarer


def _failure_context() -> FailureContext:
    out = Output(
        task_id="t", agent_id="a", content="réponse ratée bidon",
        llm_metadata=LLMMetadata(model_name="m", tokens_in=1, tokens_out=1, latency_ms=1.0),
    )
    qa = QAResult(task_id="t", agent_id="a", success=False, score=0.2,
                  reason="trop court", criteria_results={"min_length": False})
    return FailureContext(failed_output=out, qa_result=qa,
                          diagnostic_reason="les critères étaient trop stricts")


class TestBuildLLMSpecInformed:
    def test_prompt_includes_failure_details(self):
        client = _FakeParseClient(_LLMEvaluatorSpec(criteria=[]))
        build_llm_spec(make_task(), client, failure_context=_failure_context())
        prompt = client.captured_kwargs["messages"][1]["content"]
        assert "Échec précédent" in prompt
        assert "réponse ratée bidon" in prompt          # output raté
        assert "trop court" in prompt                    # raison QA
        assert "les critères étaient trop stricts" in prompt  # diagnostic
        assert "min_length" in prompt                    # critère raté

    def test_none_failure_context_matches_cold_start(self):
        c1 = _FakeParseClient(_LLMEvaluatorSpec(criteria=[]))
        c2 = _FakeParseClient(_LLMEvaluatorSpec(criteria=[]))
        build_llm_spec(make_task(), c1)
        build_llm_spec(make_task(), c2, failure_context=None)
        assert c1.captured_kwargs["messages"][1]["content"] == \
            c2.captured_kwargs["messages"][1]["content"]
