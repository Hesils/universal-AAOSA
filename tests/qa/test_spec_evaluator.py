import pytest

import aaosa.qa.spec_evaluator as se_module
from aaosa.qa.judge import DimensionScore, JudgeResult
from aaosa.qa.protocol import QAEvaluator, QAResult
from aaosa.qa.spec import CriterionSpec, EvaluatorSpec, JudgeSpec
from aaosa.qa.spec_evaluator import SpecEvaluator, from_spec
from aaosa.schemas.output import Output, LLMMetadata
from aaosa.schemas.task import Task


def make_task() -> Task:
    return Task(description="do x", required_tags={"python": 80})


def make_output(content: str) -> Output:
    return Output(
        task_id="t1", agent_id="a1", content=content,
        llm_metadata=LLMMetadata(model_name="m", tokens_in=1, tokens_out=1, latency_ms=1.0),
    )


class TestProtocolCompliance:
    def test_satisfies_qaevaluator(self):
        ev = SpecEvaluator(EvaluatorSpec(criteria=[CriterionSpec(name="non_empty", gate=True)]))
        assert isinstance(ev, QAEvaluator)

    def test_returns_qaresult(self):
        ev = SpecEvaluator(EvaluatorSpec(criteria=[CriterionSpec(name="non_empty", gate=True)]))
        r = ev.evaluate(make_task(), make_output("hello world"))
        assert isinstance(r, QAResult)
        assert r.task_id == make_task().id or r.task_id  # task_id renseigné


class TestGates:
    def test_gate_fail_short_circuits(self):
        spec = EvaluatorSpec(criteria=[CriterionSpec(name="non_empty", gate=True)])
        r = SpecEvaluator(spec).evaluate(make_task(), make_output(""))
        assert r.success is False
        assert r.score == 0.0
        assert "gate failed" in r.reason
        assert r.criteria_results["non_empty"] is False

    def test_all_gates_pass(self):
        spec = EvaluatorSpec(criteria=[CriterionSpec(name="non_empty", gate=True)],
                             success_threshold=0.5)
        r = SpecEvaluator(spec).evaluate(make_task(), make_output("hello"))
        assert r.success is True


class TestScoredCombination:
    def test_weighted_average(self):
        # min_length scoré (content 25 chars → score 0.5) avec seuil 0.4 → success
        spec = EvaluatorSpec(
            criteria=[CriterionSpec(name="min_length", weight=1.0)],
            success_threshold=0.4,
        )
        r = SpecEvaluator(spec).evaluate(make_task(), make_output("x" * 25))
        assert r.score == pytest.approx(0.5)
        assert r.success is True

    def test_no_scored_criteria_score_is_one(self):
        spec = EvaluatorSpec(criteria=[CriterionSpec(name="non_empty", gate=True)],
                             success_threshold=0.9)
        r = SpecEvaluator(spec).evaluate(make_task(), make_output("hello"))
        assert r.score == pytest.approx(1.0)
        assert r.success is True

    def test_threshold_not_met(self):
        spec = EvaluatorSpec(
            criteria=[CriterionSpec(name="min_length", weight=1.0)],
            success_threshold=0.9,
        )
        r = SpecEvaluator(spec).evaluate(make_task(), make_output("x" * 25))  # score 0.5
        assert r.success is False


class TestJudgeCombination:
    def test_judge_combined_linearly(self, monkeypatch):
        # det_score = 1.0 (min_length pass, 60 chars), judge.overall = 0.0, weight 0.5 → final 0.5
        monkeypatch.setattr(
            se_module, "run_judge",
            lambda task, output, spec, client, reference=None: JudgeResult(
                dimension_scores=[], overall=0.0, reason="bad"),
        )
        spec = EvaluatorSpec(
            criteria=[CriterionSpec(name="min_length", weight=1.0)],
            judge=JudgeSpec(rubric=["correctness"], weight=0.5),
            success_threshold=0.6,
        )
        r = SpecEvaluator(spec, client=object()).evaluate(make_task(), make_output("x" * 60))
        assert r.score == pytest.approx(0.5)   # (1-0.5)*1.0 + 0.5*0.0
        assert r.success is False               # 0.5 < 0.6

    def test_judge_skipped_when_gate_fails(self, monkeypatch):
        called = {"n": 0}
        def _spy(*a, **k):
            called["n"] += 1
            return JudgeResult(dimension_scores=[], overall=1.0, reason="")
        monkeypatch.setattr(se_module, "run_judge", _spy)
        spec = EvaluatorSpec(
            criteria=[CriterionSpec(name="non_empty", gate=True)],
            judge=JudgeSpec(rubric=["x"], weight=0.5),
        )
        SpecEvaluator(spec, client=object()).evaluate(make_task(), make_output(""))
        assert called["n"] == 0   # judge jamais appelé si gate échoue

    def test_reference_passed_to_judge(self, monkeypatch):
        seen = {}
        def _capture(task, output, spec, client, reference=None):
            seen["reference"] = reference
            return JudgeResult(dimension_scores=[], overall=1.0, reason="")
        monkeypatch.setattr(se_module, "run_judge", _capture)
        spec = EvaluatorSpec(
            criteria=[CriterionSpec(name="non_empty", gate=True)],
            judge=JudgeSpec(mode="reference_based", rubric=["x"]),
            success_threshold=0.5,
        )
        SpecEvaluator(spec, client=object(), reference="IDEAL").evaluate(make_task(), make_output("hi"))
        assert seen["reference"] == "IDEAL"


class TestConstruction:
    def test_judge_without_client_raises(self):
        spec = EvaluatorSpec(
            criteria=[CriterionSpec(name="non_empty", gate=True)],
            judge=JudgeSpec(rubric=["x"]),
        )
        with pytest.raises(ValueError, match="client"):
            SpecEvaluator(spec, client=None)

    def test_from_spec_returns_evaluator(self):
        ev = from_spec(EvaluatorSpec(criteria=[CriterionSpec(name="non_empty", gate=True)]))
        assert isinstance(ev, SpecEvaluator)


class TestQAResultJudgeBreakdown:
    def test_judge_breakdown_populated_when_judge_runs(self, monkeypatch):
        spec = EvaluatorSpec(
            criteria=[CriterionSpec(name="non_empty", gate=True)],
            judge=JudgeSpec(rubric=["clarity"], weight=0.3, mode="rubric"),
            success_threshold=0.5,
        )
        judge_result = JudgeResult(
            dimension_scores=[DimensionScore(name="clarity", score=0.8)],
            overall=0.8, reason="clear",
        )
        monkeypatch.setattr(
            se_module, "run_judge",
            lambda task, output, spec, client, reference=None: judge_result,
        )
        evaluator = from_spec(spec, client=object())

        task = make_task()
        output = make_output("a sufficiently long answer about python " * 3)
        result = evaluator.evaluate(task, output)

        assert result.judge is not None
        assert result.judge.mode == "rubric"
        assert result.judge.overall == 0.8
        assert result.judge.reason == "clear"
        assert result.judge.dimension_scores[0].name == "clarity"

    def test_judge_none_when_no_judge(self):
        spec = EvaluatorSpec(criteria=[CriterionSpec(name="non_empty", gate=True)])
        evaluator = from_spec(spec)
        task = make_task()
        output = make_output("non empty")
        result = evaluator.evaluate(task, output)
        assert result.judge is None


from types import SimpleNamespace


class _LLMCheckClient:
    """Mock le micro-appel de llm_check : parse() -> parsed{score, reason}.

    Expose .parse(**kwargs) -> parsed object directement (pattern provider.parse).
    """
    def __init__(self, score: float, reason: str = "ok"):
        self._parsed = SimpleNamespace(score=score, reason=reason)

    def parse(self, **kwargs):
        return self._parsed


class TestLLMCheckIntegration:
    def test_llm_check_client_injected(self):
        # Sans le fix, llm_check lève "requires a 'client' in params".
        spec = EvaluatorSpec(
            criteria=[
                CriterionSpec(name="non_empty", gate=True),
                CriterionSpec(name="llm_check",
                              params={"description": "must mention indexing"}, weight=1.0),
            ],
            success_threshold=0.5,
        )
        ev = SpecEvaluator(spec, client=_LLMCheckClient(score=0.9))
        r = ev.evaluate(make_task(), make_output("use a DB index on the token column"))
        assert r.criteria_results["llm_check"] is True
        assert r.success is True

    def test_llm_check_without_client_raises_at_construction(self):
        spec = EvaluatorSpec(
            criteria=[
                CriterionSpec(name="non_empty", gate=True),
                CriterionSpec(name="llm_check", params={"description": "x"}, weight=1.0),
            ],
        )
        with pytest.raises(ValueError, match="client"):
            SpecEvaluator(spec, client=None)

    def test_spec_used_populated(self):
        spec = EvaluatorSpec(criteria=[CriterionSpec(name="non_empty", gate=True)],
                             success_threshold=0.5)
        r = SpecEvaluator(spec).evaluate(make_task(), make_output("hello"))
        assert r.spec_used == spec


from aaosa.qa.spec_evaluator import AdaptiveSpecEvaluator


class TestAdaptiveSpecEvaluator:
    def test_satisfies_protocol(self):
        assert isinstance(AdaptiveSpecEvaluator(client=object()), QAEvaluator)

    def test_evaluate_builds_spec_per_task_and_delegates(self, monkeypatch):
        known = EvaluatorSpec(criteria=[CriterionSpec(name="non_empty", gate=True)],
                              success_threshold=0.5)
        calls = {"n": 0}
        def fake_build(task, client, failure_context=None):
            calls["n"] += 1
            return known
        monkeypatch.setattr(se_module, "build_llm_spec", fake_build)

        ev = AdaptiveSpecEvaluator(client=object())
        r = ev.evaluate(make_task(), make_output("hello world"))
        assert calls["n"] == 1
        assert r.success is True
        assert r.spec_used == known


from aaosa.qa.diagnostic import FailureContext


def _fc():
    out = make_output("bad")
    qa = QAResult(task_id="t", agent_id="a1", success=False, score=0.1,
                  reason="r", criteria_results={})
    return FailureContext(failed_output=out, qa_result=qa, diagnostic_reason="d")


class TestAdaptiveSpecEvaluatorFailureContext:
    def test_default_failure_context_is_none(self):
        ev = AdaptiveSpecEvaluator(client=None)
        assert ev.failure_context is None

    def test_stores_failure_context(self):
        fc = _fc()
        ev = AdaptiveSpecEvaluator(client=None, failure_context=fc)
        assert ev.failure_context is fc

    def test_evaluate_passes_failure_context_to_build(self, monkeypatch):
        captured = {}

        def fake_build(task, client, failure_context=None):
            captured["fc"] = failure_context
            return EvaluatorSpec(criteria=[CriterionSpec(name="non_empty", gate=True)])

        monkeypatch.setattr(se_module, "build_llm_spec", fake_build)
        fc = _fc()
        AdaptiveSpecEvaluator(client=None, failure_context=fc).evaluate(
            make_task(), make_output("x")
        )
        assert captured["fc"] is fc


from aaosa.qa.criteria import CRITERIA_REGISTRY, CriterionOutcome


class TestDistinctKeys:
    def test_single_name_not_suffixed(self):
        spec = EvaluatorSpec(
            criteria=[CriterionSpec(name="min_length", weight=1.0)],
            success_threshold=0.0,
        )
        r = SpecEvaluator(spec).evaluate(make_task(), make_output("x" * 100))
        assert "min_length" in r.criteria_results
        assert "min_length#1" not in r.criteria_results

    def test_duplicate_names_get_distinct_keys(self, monkeypatch):
        # deux critères de même name → deux clés distinctes, les deux scorés
        def stub(task, output, params):
            return CriterionOutcome(name="dup", passed=True, score=1.0, detail="ok")

        monkeypatch.setitem(CRITERIA_REGISTRY, "dup", stub)
        spec = EvaluatorSpec(
            criteria=[
                CriterionSpec(name="dup", weight=1.0),
                CriterionSpec(name="dup", weight=1.0),
            ],
            success_threshold=0.0,
        )
        r = SpecEvaluator(spec).evaluate(make_task(), make_output("hello"))
        assert "dup#1" in r.criteria_results
        assert "dup#2" in r.criteria_results

    def test_duplicate_gate_keys_distinct(self, monkeypatch):
        def stub(task, output, params):
            return CriterionOutcome(name="g", passed=True, score=1.0, detail="ok")

        monkeypatch.setitem(CRITERIA_REGISTRY, "g", stub)
        spec = EvaluatorSpec(
            criteria=[
                CriterionSpec(name="g", gate=True),
                CriterionSpec(name="g", gate=True),
            ],
            success_threshold=0.0,
        )
        r = SpecEvaluator(spec).evaluate(make_task(), make_output("hello"))
        assert "g#1" in r.criteria_results and "g#2" in r.criteria_results
