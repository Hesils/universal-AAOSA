import pytest

from aaosa.qa.judge import JudgeResult, run_judge
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


class _FakeMessage:
    def __init__(self, parsed):
        self.parsed = parsed

class _FakeChoice:
    def __init__(self, parsed):
        self.message = _FakeMessage(parsed)

class _FakeParseResponse:
    def __init__(self, parsed):
        self.choices = [_FakeChoice(parsed)]

class FakeParseClient:
    """Capture les kwargs et retourne un JudgeResult pré-calculé."""
    def __init__(self, parsed: JudgeResult):
        self._parsed = parsed
        self.captured_kwargs = None
        self.beta = self
        self.chat = self
        self.completions = self

    def parse(self, **kwargs):
        self.captured_kwargs = kwargs
        return _FakeParseResponse(self._parsed)


class TestJudgeResult:
    def test_valid(self):
        r = JudgeResult(dimension_scores={"correctness": 0.9}, overall=0.9, reason="good")
        assert r.overall == 0.9

    def test_extra_forbidden(self):
        with pytest.raises(Exception):
            JudgeResult(dimension_scores={}, overall=1.0, reason="", bogus=1)


class TestRunJudge:
    def test_returns_judge_result(self):
        expected = JudgeResult(dimension_scores={"correctness": 0.8}, overall=0.8, reason="ok")
        client = FakeParseClient(expected)
        result = run_judge(make_task(), make_output(), JudgeSpec(rubric=["correctness"]), client)
        assert result.overall == 0.8

    def test_uses_spec_model_and_temperature(self):
        client = FakeParseClient(JudgeResult(dimension_scores={"x": 1.0}, overall=1.0, reason=""))
        spec = JudgeSpec(rubric=["x"], model="gpt-4o-mini", temperature=0.0)
        run_judge(make_task(), make_output(), spec, client)
        assert client.captured_kwargs["model"] == "gpt-4o-mini"
        assert client.captured_kwargs["temperature"] == 0.0
        assert client.captured_kwargs["response_format"] is JudgeResult

    def test_rubric_mode_no_reference_in_prompt(self):
        client = FakeParseClient(JudgeResult(dimension_scores={"x": 1.0}, overall=1.0, reason=""))
        run_judge(make_task(), make_output(), JudgeSpec(mode="rubric", rubric=["x"]), client)
        user_msg = client.captured_kwargs["messages"][-1]["content"]
        assert "Reference" not in user_msg and "référence" not in user_msg.lower()

    def test_reference_based_injects_reference(self):
        client = FakeParseClient(JudgeResult(dimension_scores={"x": 1.0}, overall=1.0, reason=""))
        spec = JudgeSpec(mode="reference_based", rubric=["x"])
        run_judge(make_task(), make_output(), spec, client, reference="THE IDEAL ANSWER")
        user_msg = client.captured_kwargs["messages"][-1]["content"]
        assert "THE IDEAL ANSWER" in user_msg

    def test_rubric_dimensions_in_prompt(self):
        client = FakeParseClient(JudgeResult(dimension_scores={}, overall=0.5, reason=""))
        run_judge(make_task(), make_output(), JudgeSpec(rubric=["correctness", "completeness"]), client)
        user_msg = client.captured_kwargs["messages"][-1]["content"]
        assert "correctness" in user_msg and "completeness" in user_msg

    def test_instructions_injected(self):
        client = FakeParseClient(JudgeResult(dimension_scores={}, overall=0.5, reason=""))
        spec = JudgeSpec(rubric=["x"], instructions="Be strict about accessibility.")
        run_judge(make_task(), make_output(), spec, client)
        user_msg = client.captured_kwargs["messages"][-1]["content"]
        assert "accessibility" in user_msg
