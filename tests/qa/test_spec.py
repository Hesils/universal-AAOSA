import pytest

from aaosa.qa.spec import CriterionSpec, JudgeSpec, EvaluatorSpec


class TestCriterionSpec:
    def test_defaults(self):
        c = CriterionSpec(name="non_empty")
        assert c.params == {}
        assert c.weight == 1.0
        assert c.gate is False

    def test_full(self):
        c = CriterionSpec(name="min_length", params={"min_chars": 100}, weight=2.0, gate=True)
        assert c.params["min_chars"] == 100
        assert c.gate is True

    def test_extra_forbidden(self):
        with pytest.raises(Exception):
            CriterionSpec(name="x", bogus=1)


class TestJudgeSpec:
    def test_defaults(self):
        j = JudgeSpec(rubric=["correctness"])
        assert j.mode == "rubric"
        assert j.model == "gpt-4o-mini"
        assert j.weight == 0.3
        assert j.temperature == 0.0
        assert j.instructions == ""

    def test_reference_based(self):
        j = JudgeSpec(mode="reference_based", rubric=["correctness", "completeness"], weight=0.5)
        assert j.mode == "reference_based"
        assert len(j.rubric) == 2

    def test_invalid_mode(self):
        with pytest.raises(Exception):
            JudgeSpec(mode="bogus", rubric=["x"])

    def test_extra_forbidden(self):
        with pytest.raises(Exception):
            JudgeSpec(rubric=["x"], bogus=1)


class TestEvaluatorSpec:
    def test_minimal(self):
        s = EvaluatorSpec(criteria=[CriterionSpec(name="non_empty", gate=True)])
        assert s.judge is None
        assert s.success_threshold == 0.7

    def test_with_judge(self):
        s = EvaluatorSpec(
            criteria=[CriterionSpec(name="non_empty", gate=True)],
            judge=JudgeSpec(rubric=["correctness"]),
            success_threshold=0.8,
        )
        assert s.judge is not None
        assert s.success_threshold == 0.8

    def test_json_roundtrip(self):
        s = EvaluatorSpec(
            criteria=[
                CriterionSpec(name="non_empty", gate=True),
                CriterionSpec(name="min_length", params={"min_chars": 80}, weight=2.0),
            ],
            judge=JudgeSpec(mode="reference_based", rubric=["a", "b"], weight=0.4),
            success_threshold=0.75,
        )
        data = s.model_dump_json()
        s2 = EvaluatorSpec.model_validate_json(data)
        assert s2 == s

    def test_extra_forbidden(self):
        with pytest.raises(Exception):
            EvaluatorSpec(criteria=[], bogus=1)
