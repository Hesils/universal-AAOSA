from types import SimpleNamespace

import pytest

from aaosa.qa.criteria import (
    CriterionOutcome,
    CRITERIA_REGISTRY,
    register_criterion,
    get_criterion,
    non_empty,
    min_length,
    references_tags,
    keyword_presence,
    format_check,
    llm_check,
)
from aaosa.schemas.output import Output, LLMMetadata
from aaosa.schemas.task import Task


class _FakeParseProvider:
    """Mocks a LLMProvider where .parse(**kwargs) -> parsed object directly."""

    def __init__(self, parsed):
        self._parsed = parsed
        self.captured_kwargs = None

    def parse(self, **kwargs):
        self.captured_kwargs = kwargs
        return self._parsed


def make_task(required_tags=None, description="Do the thing") -> Task:
    return Task(description=description, required_tags=required_tags or {"python": 80})


def make_output(content: str) -> Output:
    return Output(
        task_id="t1",
        agent_id="a1",
        content=content,
        llm_metadata=LLMMetadata(model_name="m", tokens_in=1, tokens_out=1, latency_ms=1.0),
    )


class TestCriterionOutcome:
    def test_valid(self):
        o = CriterionOutcome(name="x", passed=True, score=1.0, detail="ok")
        assert o.score == 1.0

    def test_extra_forbidden(self):
        with pytest.raises(Exception):
            CriterionOutcome(name="x", passed=True, score=1.0, detail="ok", bogus=1)


class TestRegistry:
    def test_library_registered(self):
        for name in ["non_empty", "min_length", "references_tags", "keyword_presence", "format_check"]:
            assert name in CRITERIA_REGISTRY

    def test_get_criterion_returns_callable(self):
        fn = get_criterion("non_empty")
        assert callable(fn)

    def test_get_unknown_raises(self):
        with pytest.raises(ValueError, match="unknown criterion"):
            get_criterion("does_not_exist")

    def test_register_decorator(self):
        @register_criterion("tmp_test_criterion")
        def _crit(task, output, params):
            return CriterionOutcome(name="tmp_test_criterion", passed=True, score=1.0, detail="")
        assert "tmp_test_criterion" in CRITERIA_REGISTRY
        del CRITERIA_REGISTRY["tmp_test_criterion"]


class TestNonEmpty:
    def test_pass(self):
        o = non_empty(make_task(), make_output("hello"), {})
        assert o.passed is True and o.score == 1.0

    def test_fail_empty(self):
        o = non_empty(make_task(), make_output(""), {})
        assert o.passed is False and o.score == 0.0

    def test_fail_whitespace(self):
        o = non_empty(make_task(), make_output("   \n  "), {})
        assert o.passed is False


class TestMinLength:
    def test_pass_default(self):
        o = min_length(make_task(), make_output("x" * 60), {})
        assert o.passed is True and o.score == 1.0

    def test_fail_short(self):
        o = min_length(make_task(), make_output("x" * 25), {})
        assert o.passed is False
        assert o.score == pytest.approx(0.5)  # 25/50

    def test_custom_threshold(self):
        o = min_length(make_task(), make_output("x" * 10), {"min_chars": 10})
        assert o.passed is True and o.score == 1.0


class TestReferencesTags:
    def test_all_present(self):
        task = make_task({"python": 80, "testing": 50})
        o = references_tags(task, make_output("uses python and testing here"), {})
        assert o.passed is True and o.score == 1.0

    def test_partial(self):
        task = make_task({"python": 80, "docker": 50})
        o = references_tags(task, make_output("only python mentioned"), {})
        assert o.passed is False
        assert o.score == pytest.approx(0.5)

    def test_custom_tags_param(self):
        o = references_tags(make_task(), make_output("contains alpha"), {"tags": ["alpha"]})
        assert o.passed is True


class TestKeywordPresence:
    def test_all_present(self):
        o = keyword_presence(make_task(), make_output("def foo(): return"), {"keywords": ["def", "return"]})
        assert o.passed is True and o.score == 1.0

    def test_partial(self):
        o = keyword_presence(make_task(), make_output("def foo()"), {"keywords": ["def", "return"]})
        assert o.score == pytest.approx(0.5)

    def test_no_keywords_passes(self):
        o = keyword_presence(make_task(), make_output("anything"), {"keywords": []})
        assert o.passed is True and o.score == 1.0


class TestFormatCheck:
    def test_json_valid(self):
        o = format_check(make_task(), make_output('{"a": 1}'), {"kind": "json"})
        assert o.passed is True

    def test_json_invalid(self):
        o = format_check(make_task(), make_output("not json"), {"kind": "json"})
        assert o.passed is False

    def test_code_block(self):
        o = format_check(make_task(), make_output("text\n```py\nx=1\n```"), {"kind": "code_block"})
        assert o.passed is True

    def test_non_empty_lines_default(self):
        o = format_check(make_task(), make_output("line one\nline two"), {})
        assert o.passed is True

    def test_non_empty_lines_fail(self):
        o = format_check(make_task(), make_output("\n   \n"), {"kind": "non_empty_lines"})
        assert o.passed is False


class TestLLMCheck:
    def test_registered(self):
        assert "llm_check" in CRITERIA_REGISTRY

    def test_passes_when_llm_says_yes(self):
        provider = _FakeParseProvider(SimpleNamespace(score=1.0, reason="meets the criterion"))
        o = llm_check(
            make_task(),
            make_output("a detailed answer with code examples"),
            {"description": "must include code examples", "client": provider},
        )
        assert o.passed is True
        assert o.score == 1.0

    def test_fails_when_llm_says_no(self):
        provider = _FakeParseProvider(SimpleNamespace(score=0.0, reason="missing examples"))
        o = llm_check(
            make_task(),
            make_output("a vague answer"),
            {"description": "must include code examples", "client": provider},
        )
        assert o.passed is False
        assert o.score == 0.0

    def test_missing_description_raises(self):
        provider = _FakeParseProvider(SimpleNamespace(score=1.0, reason="ok"))
        with pytest.raises(ValueError):
            llm_check(make_task(), make_output("x"), {"client": provider})
