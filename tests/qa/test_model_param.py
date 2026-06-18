"""Task 5 — model param threaded through evaluator (adaptive spec + llm_check).

Tests written BEFORE implementation (TDD RED phase).

Coverage:
- build_llm_spec(..., model="m") relays model="m" to provider.parse
- llm_check with params {"model": "m"} relays model="m" to provider.parse
- AdaptiveSpecEvaluator(fake, model="m").evaluate causes
    build_llm_spec parse to see model="m" AND any llm_check parse to see model="m"
- SpecEvaluator(spec, model="m") passes model="m" into criterion params for both
    gate and scored criteria
- from_spec relays model to SpecEvaluator
- Judge invariant: run_judge still receives spec.model (NOT the evaluator model)
"""
from types import SimpleNamespace

import pytest

import aaosa.qa.spec_evaluator as se_module
from aaosa.qa.adaptive import build_llm_spec, _LLMEvaluatorSpec, _LLMCriterion
from aaosa.qa.criteria import llm_check, CRITERIA_REGISTRY, CriterionOutcome
from aaosa.qa.judge import JudgeResult
from aaosa.qa.protocol import QAResult
from aaosa.qa.spec import CriterionSpec, EvaluatorSpec, JudgeSpec
from aaosa.qa.spec_evaluator import AdaptiveSpecEvaluator, SpecEvaluator, from_spec
from aaosa.schemas.output import LLMMetadata, Output
from aaosa.schemas.task import Task


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_task() -> Task:
    return Task(description="Explain indexing", required_tags={"db": 50})


def make_output(content: str = "hello world") -> Output:
    return Output(
        task_id="t1",
        agent_id="a1",
        content=content,
        llm_metadata=LLMMetadata(model_name="m", tokens_in=1, tokens_out=1, latency_ms=1.0),
    )


class _CaptureProvider:
    """Provider that records ALL calls to parse() and returns a preset value."""

    def __init__(self, return_value):
        self._return = return_value
        self.calls: list[dict] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return self._return


# ---------------------------------------------------------------------------
# 1. build_llm_spec relays model to provider.parse
# ---------------------------------------------------------------------------

class TestBuildLLMSpecModelParam:
    def test_model_relayed_to_provider_parse(self):
        llm_spec = _LLMEvaluatorSpec(
            criteria=[_LLMCriterion(type="min_length", min_chars=50)]
        )
        provider = _CaptureProvider(llm_spec)
        build_llm_spec(make_task(), provider, model="gpt-4o-mini")
        assert len(provider.calls) == 1
        assert provider.calls[0].get("model") == "gpt-4o-mini"

    def test_model_none_by_default(self):
        llm_spec = _LLMEvaluatorSpec(
            criteria=[_LLMCriterion(type="min_length", min_chars=50)]
        )
        provider = _CaptureProvider(llm_spec)
        build_llm_spec(make_task(), provider)
        # model key may be absent or None — both are valid "default" behaviours
        assert provider.calls[0].get("model") is None

    def test_model_not_leaked_when_none(self):
        """When model=None, parse must still be called (no crash)."""
        llm_spec = _LLMEvaluatorSpec(criteria=[])
        provider = _CaptureProvider(llm_spec)
        build_llm_spec(make_task(), provider, model=None)
        assert len(provider.calls) == 1

    def test_failure_context_and_model_together(self):
        """model and failure_context are orthogonal — both relayed correctly."""
        from aaosa.qa.diagnostic import FailureContext

        bad_out = make_output("bad")
        qa = QAResult(
            task_id="t", agent_id="a1", success=False, score=0.1,
            reason="r", criteria_results={},
        )
        fc = FailureContext(failed_output=bad_out, qa_result=qa, diagnostic_reason="d")
        llm_spec = _LLMEvaluatorSpec(criteria=[])
        provider = _CaptureProvider(llm_spec)
        build_llm_spec(make_task(), provider, failure_context=fc, model="custom-model")
        assert provider.calls[0].get("model") == "custom-model"


# ---------------------------------------------------------------------------
# 2. llm_check criterion relays model from params to provider.parse
# ---------------------------------------------------------------------------

class TestLLMCheckModelParam:
    def test_model_relayed_when_present(self):
        parsed = SimpleNamespace(score=0.9, reason="good")
        provider = _CaptureProvider(parsed)
        llm_check(
            make_task(),
            make_output("some detailed answer"),
            {"description": "must be detailed", "provider": provider, "model": "eval-model-x"},
        )
        assert provider.calls[0].get("model") == "eval-model-x"

    def test_model_none_when_absent(self):
        parsed = SimpleNamespace(score=0.9, reason="good")
        provider = _CaptureProvider(parsed)
        llm_check(
            make_task(),
            make_output("some answer"),
            {"description": "check something", "provider": provider},
        )
        # model key absent or None — should not crash
        assert provider.calls[0].get("model") is None

    def test_other_criteria_unaffected_by_model_in_params(self):
        """min_length and friends must not crash when model key is in params."""
        from aaosa.qa.criteria import min_length
        # min_length ignores "model" — should not raise
        outcome = min_length(
            make_task(),
            make_output("x" * 60),
            {"model": "some-model"},
        )
        assert outcome.passed is True


# ---------------------------------------------------------------------------
# 3. SpecEvaluator stores and injects model into criterion params
# ---------------------------------------------------------------------------

class TestSpecEvaluatorModelParam:
    def _make_spec_with_llm_check(self) -> EvaluatorSpec:
        return EvaluatorSpec(
            criteria=[
                CriterionSpec(name="non_empty", gate=True),
                CriterionSpec(
                    name="llm_check",
                    params={"description": "must be useful"},
                    weight=1.0,
                ),
            ],
            success_threshold=0.5,
        )

    def test_stores_model(self):
        spec = EvaluatorSpec(criteria=[CriterionSpec(name="non_empty", gate=True)])
        ev = SpecEvaluator(spec, model="my-model")
        assert ev.model == "my-model"

    def test_model_defaults_to_none(self):
        spec = EvaluatorSpec(criteria=[CriterionSpec(name="non_empty", gate=True)])
        ev = SpecEvaluator(spec)
        assert ev.model is None

    def test_model_injected_into_gate_criterion_params(self, monkeypatch):
        """model is passed into params for gate criteria."""
        captured_params: list[dict] = []

        def fake_non_empty(task, output, params):
            captured_params.append(dict(params))
            return CriterionOutcome(name="non_empty", passed=True, score=1.0, detail="ok")

        monkeypatch.setitem(CRITERIA_REGISTRY, "non_empty", fake_non_empty)
        spec = EvaluatorSpec(
            criteria=[CriterionSpec(name="non_empty", gate=True)],
            success_threshold=0.5,
        )
        SpecEvaluator(spec, model="gate-model").evaluate(make_task(), make_output("hi"))
        assert captured_params[0].get("model") == "gate-model"

    def test_model_injected_into_scored_criterion_params(self, monkeypatch):
        """model is passed into params for scored criteria."""
        captured_params: list[dict] = []

        def fake_min_length(task, output, params):
            captured_params.append(dict(params))
            return CriterionOutcome(name="min_length", passed=True, score=1.0, detail="ok")

        monkeypatch.setitem(CRITERIA_REGISTRY, "min_length", fake_min_length)
        spec = EvaluatorSpec(
            criteria=[CriterionSpec(name="min_length", weight=1.0)],
            success_threshold=0.5,
        )
        SpecEvaluator(spec, model="scored-model").evaluate(make_task(), make_output("hi"))
        assert captured_params[0].get("model") == "scored-model"

    def test_llm_check_receives_evaluator_model(self):
        """End-to-end: evaluator model reaches llm_check's provider.parse call."""
        parsed = SimpleNamespace(score=0.9, reason="great")
        provider = _CaptureProvider(parsed)

        spec = self._make_spec_with_llm_check()
        ev = SpecEvaluator(spec, client=provider, model="eval-model-42")
        ev.evaluate(make_task(), make_output("a sufficiently detailed answer about db indexing"))

        # The spec has non_empty (gate, no LLM) + llm_check (scored, calls parse).
        # All provider.parse calls must carry model="eval-model-42".
        assert len(provider.calls) >= 1, "Expected at least one provider.parse call (llm_check)"
        for call in provider.calls:
            assert call.get("model") == "eval-model-42", (
                f"A parse call did not receive the evaluator model: {call}"
            )


# ---------------------------------------------------------------------------
# 4. from_spec relays model
# ---------------------------------------------------------------------------

class TestFromSpecModelParam:
    def test_from_spec_relays_model(self):
        spec = EvaluatorSpec(criteria=[CriterionSpec(name="non_empty", gate=True)])
        ev = from_spec(spec, model="relayed-model")
        assert ev.model == "relayed-model"

    def test_from_spec_model_none_default(self):
        spec = EvaluatorSpec(criteria=[CriterionSpec(name="non_empty", gate=True)])
        ev = from_spec(spec)
        assert ev.model is None


# ---------------------------------------------------------------------------
# 5. AdaptiveSpecEvaluator stores and propagates model
# ---------------------------------------------------------------------------

class TestAdaptiveSpecEvaluatorModelParam:
    def test_stores_model(self):
        ev = AdaptiveSpecEvaluator(client=object(), model="adaptive-model")
        assert ev.model == "adaptive-model"

    def test_model_defaults_to_none(self):
        ev = AdaptiveSpecEvaluator(client=object())
        assert ev.model is None

    def test_evaluate_passes_model_to_build_llm_spec(self, monkeypatch):
        """build_llm_spec called with model=self.model."""
        captured = {}

        def fake_build(task, provider, failure_context=None, model=None):
            captured["model"] = model
            return EvaluatorSpec(criteria=[CriterionSpec(name="non_empty", gate=True)])

        monkeypatch.setattr(se_module, "build_llm_spec", fake_build)
        ev = AdaptiveSpecEvaluator(client=object(), model="my-llm")
        ev.evaluate(make_task(), make_output("hello"))
        assert captured["model"] == "my-llm"

    def test_evaluate_passes_model_to_spec_evaluator(self, monkeypatch):
        """SpecEvaluator inside evaluate receives model=self.model."""
        captured = {}
        known_spec = EvaluatorSpec(criteria=[CriterionSpec(name="non_empty", gate=True)])

        def fake_build(task, provider, failure_context=None, model=None):
            return known_spec

        original_se_init = SpecEvaluator.__init__

        def fake_se_init(self_se, spec, client=None, reference=None, model=None):
            captured["se_model"] = model
            original_se_init(self_se, spec, client=client, reference=reference, model=model)

        monkeypatch.setattr(se_module, "build_llm_spec", fake_build)
        monkeypatch.setattr(SpecEvaluator, "__init__", fake_se_init)
        ev = AdaptiveSpecEvaluator(client=object(), model="propagated-model")
        ev.evaluate(make_task(), make_output("hello"))
        assert captured["se_model"] == "propagated-model"

    def test_evaluate_llm_check_parse_sees_evaluator_model(self, monkeypatch):
        """Integration: evaluator model reaches llm_check's provider.parse."""
        parsed_llm_check = SimpleNamespace(score=0.9, reason="ok")
        llm_spec = _LLMEvaluatorSpec(
            criteria=[_LLMCriterion(type="llm_check", description="must be detailed")]
        )
        provider = _CaptureProvider(None)

        call_count = [0]

        def smart_parse(**kwargs):
            call_count[0] += 1
            # First call: build_llm_spec parse → return llm_spec
            if call_count[0] == 1:
                return llm_spec
            # Subsequent calls: llm_check parse → return scored result
            return parsed_llm_check

        provider.parse = lambda **kwargs: (  # type: ignore
            (lambda: (provider.calls.append(kwargs), smart_parse(**kwargs))[1])()
        )

        ev = AdaptiveSpecEvaluator(client=provider, model="end-to-end-model")
        ev.evaluate(make_task(), make_output("a detailed answer about DB indexing strategies"))

        # All parse calls must have received model="end-to-end-model"
        for call in provider.calls:
            assert call.get("model") == "end-to-end-model", (
                f"A parse call did not receive the expected model: {call}"
            )


# ---------------------------------------------------------------------------
# 6. Judge invariant: run_judge receives spec.model, NOT evaluator model
# ---------------------------------------------------------------------------

class TestJudgeModelInvariant:
    """The evaluator model must NOT bleed into run_judge.

    run_judge uses spec.model (from JudgeSpec) for its LLM call.
    This is invariant V2b (judge never the primary signal).
    """

    def test_run_judge_called_with_spec_judge_not_evaluator_model(self, monkeypatch):
        """Capture what run_judge receives; assert it's called with the judge spec,
        not with the evaluator's model override."""
        captured = {}

        def fake_run_judge(task, output, spec, client, reference=None):
            captured["judge_spec"] = spec
            captured["client"] = client
            return JudgeResult(dimension_scores=[], overall=0.9, reason="good")

        monkeypatch.setattr(se_module, "run_judge", fake_run_judge)

        judge_spec = JudgeSpec(rubric=["correctness"], weight=0.3, mode="rubric")
        judge_spec_with_model = judge_spec.model_copy(update={"model": "judge-specific-model"})

        spec = EvaluatorSpec(
            criteria=[CriterionSpec(name="non_empty", gate=True)],
            judge=judge_spec_with_model,
            success_threshold=0.5,
        )
        # evaluator_model is DIFFERENT from judge model
        evaluator_model = "evaluator-model-that-must-not-reach-judge"
        ev = SpecEvaluator(spec, client=object(), model=evaluator_model)
        ev.evaluate(make_task(), make_output("some output"))

        # run_judge must have been called
        assert "judge_spec" in captured, "run_judge was never called"
        # The spec passed to run_judge must be the JudgeSpec, not the evaluator model
        assert captured["judge_spec"] is judge_spec_with_model
        # run_judge uses spec.model internally — we verify the spec carries its own model
        assert captured["judge_spec"].model == "judge-specific-model"

    def test_evaluator_model_does_not_appear_in_judge_call(self, monkeypatch):
        """run_judge signature: (task, output, spec, client, reference).
        The evaluator's model is NOT one of these positional args."""
        call_kwargs: dict = {}

        def capturing_run_judge(task, output, spec, client, reference=None):
            call_kwargs["positional_args"] = (task, output, spec, client)
            call_kwargs["reference"] = reference
            return JudgeResult(dimension_scores=[], overall=0.8, reason="fine")

        monkeypatch.setattr(se_module, "run_judge", capturing_run_judge)

        spec = EvaluatorSpec(
            criteria=[CriterionSpec(name="non_empty", gate=True)],
            judge=JudgeSpec(rubric=["correctness"], weight=0.3),
            success_threshold=0.5,
        )
        evaluator_model = "evaluator-only-model"
        ev = SpecEvaluator(spec, client=object(), model=evaluator_model)
        ev.evaluate(make_task(), make_output("hello"))

        # The evaluator model must not appear anywhere in what was passed to run_judge
        for arg in call_kwargs["positional_args"]:
            assert arg != evaluator_model, (
                f"Evaluator model leaked into run_judge positional args: {arg}"
            )
        assert call_kwargs["reference"] != evaluator_model
