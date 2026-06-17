import pytest

from aaosa.qa.judge import DimensionScore, JudgeResult, run_judge
from aaosa.qa.spec import JudgeSpec
from aaosa.schemas.output import Output, LLMMetadata
from aaosa.schemas.task import Task


def make_task() -> Task:
    return Task(description="Build a login form", required_tags={"frontend": 80})


def make_output(content="<form>login</form>") -> Output:
    return Output(
        task_id="t1", agent_id="a1", content=content,
        llm_metadata=LLMMetadata(model_name="m", tokens_in=1, tokens_out=1, latency_ms=1.0),
    )


class FakeParseProvider:
    """Captures kwargs and returns a pre-built JudgeResult via provider.parse(...)."""

    def __init__(self, parsed: JudgeResult):
        self._parsed = parsed
        self.captured_kwargs = None

    def parse(self, **kwargs):
        self.captured_kwargs = kwargs
        return self._parsed


class TestDimensionScore:
    def test_valid(self):
        d = DimensionScore(name="correctness", score=0.8)
        assert d.name == "correctness"
        assert d.score == 0.8

    def test_extra_forbidden(self):
        with pytest.raises(Exception):
            DimensionScore(name="x", score=1.0, bogus=1)


class TestJudgeResult:
    def test_valid(self):
        r = JudgeResult(
            dimension_scores=[DimensionScore(name="correctness", score=0.9)],
            overall=0.9,
            reason="good",
        )
        assert r.overall == 0.9
        assert r.dimension_scores[0].name == "correctness"

    def test_empty_dimension_scores_valid(self):
        r = JudgeResult(dimension_scores=[], overall=1.0, reason="")
        assert r.dimension_scores == []

    def test_extra_forbidden(self):
        with pytest.raises(Exception):
            JudgeResult(dimension_scores=[], overall=1.0, reason="", bogus=1)


class TestRunJudge:
    def test_returns_judge_result(self):
        expected = JudgeResult(dimension_scores=[DimensionScore(name="correctness", score=0.8)], overall=0.8, reason="ok")
        provider = FakeParseProvider(expected)
        result = run_judge(make_task(), make_output(), JudgeSpec(rubric=["correctness"]), provider)
        assert result.overall == 0.8

    def test_uses_spec_model_and_temperature(self):
        provider = FakeParseProvider(JudgeResult(dimension_scores=[], overall=1.0, reason=""))
        spec = JudgeSpec(rubric=["x"], model="gpt-4o-mini", temperature=0.0)
        run_judge(make_task(), make_output(), spec, provider)
        assert provider.captured_kwargs["model"] == "gpt-4o-mini"
        assert provider.captured_kwargs["temperature"] == 0.0
        assert provider.captured_kwargs["schema"] is JudgeResult

    def test_rubric_mode_no_reference_in_prompt(self):
        provider = FakeParseProvider(JudgeResult(dimension_scores=[], overall=1.0, reason=""))
        run_judge(make_task(), make_output(), JudgeSpec(mode="rubric", rubric=["x"]), provider)
        user_msg = provider.captured_kwargs["messages"][-1]["content"]
        assert "Reference" not in user_msg and "référence" not in user_msg.lower()

    def test_reference_based_injects_reference(self):
        provider = FakeParseProvider(JudgeResult(dimension_scores=[], overall=1.0, reason=""))
        spec = JudgeSpec(mode="reference_based", rubric=["x"])
        run_judge(make_task(), make_output(), spec, provider, reference="THE IDEAL ANSWER")
        user_msg = provider.captured_kwargs["messages"][-1]["content"]
        assert "THE IDEAL ANSWER" in user_msg

    def test_rubric_dimensions_in_prompt(self):
        provider = FakeParseProvider(JudgeResult(dimension_scores=[], overall=0.5, reason=""))
        run_judge(make_task(), make_output(), JudgeSpec(rubric=["correctness", "completeness"]), provider)
        user_msg = provider.captured_kwargs["messages"][-1]["content"]
        assert "correctness" in user_msg and "completeness" in user_msg

    def test_instructions_injected(self):
        provider = FakeParseProvider(JudgeResult(dimension_scores=[], overall=0.5, reason=""))
        spec = JudgeSpec(rubric=["x"], instructions="Be strict about accessibility.")
        run_judge(make_task(), make_output(), spec, provider)
        user_msg = provider.captured_kwargs["messages"][-1]["content"]
        assert "accessibility" in user_msg
