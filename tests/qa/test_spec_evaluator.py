import pytest

import aaosa.qa.spec_evaluator as se_module
from aaosa.qa.judge import JudgeResult
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
