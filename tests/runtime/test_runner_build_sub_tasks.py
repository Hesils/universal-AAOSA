from types import SimpleNamespace

import pytest

from aaosa.runtime.context import RunContext
from aaosa.runtime.divider import DivisionResult, SubTaskSpec
from aaosa.runtime.runner import build_sub_tasks
from aaosa.schemas.task import Task


class _StubTagger:
    def tag(self, description, agents, provider, model=None):
        return ["python"]


def _ctx() -> RunContext:
    return RunContext(
        agents=[],
        provider=SimpleNamespace(),
        divider=SimpleNamespace(),
        aggregator=SimpleNamespace(),
        tagger=_StubTagger(),
        tracer=None,
    )


def test_build_sub_tasks_propagates_context():
    parent = Task(description="parent", required_tags={"python": 50})
    division = DivisionResult(sub_tasks=[
        SubTaskSpec(description="sub A", context="focalisé A"),
        SubTaskSpec(description="sub B"),  # context None
    ])
    subs = build_sub_tasks(parent, division, _ctx())
    assert subs[0].context == "focalisé A"
    assert subs[1].context is None
