from types import SimpleNamespace

import pytest

from aaosa.qa.diagnostic import FailureContext
from aaosa.qa.protocol import QAResult
from aaosa.runtime.divider import DivisionResult, SubTaskSpec, TaskDivider
from aaosa.runtime.providers import LLMProvider
from aaosa.schemas.output import LLMMetadata, Output
from aaosa.schemas.task import Task


def _provider_returning(division_result):
    """Build a provider fake whose .parse() returns division_result."""
    return SimpleNamespace(parse=lambda **kw: division_result)


class TestDivisionResult:
    def test_non_atomic_requires_subtasks(self):
        with pytest.raises(ValueError, match="non-atomic"):
            DivisionResult(is_atomic=False, sub_tasks=[])

    def test_atomic_forbids_subtasks(self):
        with pytest.raises(ValueError, match="atomic"):
            DivisionResult(is_atomic=True, sub_tasks=[SubTaskSpec(description="x")])

    def test_atomic_ok_with_no_subtasks(self):
        d = DivisionResult(is_atomic=True, sub_tasks=[])
        assert d.is_atomic is True

    def test_subtaskspec_has_no_tags(self):
        spec = SubTaskSpec(description="x", depends_on_indices=[0])
        assert not hasattr(spec, "required_tags")


class TestTaskDivider:
    def test_divide_returns_division_result(self):
        result = DivisionResult(sub_tasks=[
            SubTaskSpec(description="a"),
            SubTaskSpec(description="b", depends_on_indices=[0]),
        ])
        divider = TaskDivider(system_prompt="split")
        out = divider.divide(Task(description="t", required_tags={"python": 30}), _provider_returning(result))
        assert isinstance(out, DivisionResult)
        assert [s.description for s in out.sub_tasks] == ["a", "b"]
        assert out.sub_tasks[1].depends_on_indices == [0]

    def test_divide_passes_through_atomic_verdict(self):
        result = DivisionResult(is_atomic=True, sub_tasks=[])
        divider = TaskDivider(system_prompt="split")
        out = divider.divide(Task(description="t", required_tags={"python": 30}), _provider_returning(result))
        assert out.is_atomic is True

    def test_divide_raises_on_none_parsed(self):
        divider = TaskDivider(system_prompt="split")
        with pytest.raises(ValueError, match="no parsed"):
            divider.divide(Task(description="t", required_tags={"python": 30}), _provider_returning(None))
