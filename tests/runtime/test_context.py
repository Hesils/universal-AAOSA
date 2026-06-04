import dataclasses

import pytest

from aaosa.core.agent import Agent
from aaosa.runtime.aggregator import TaskAggregator
from aaosa.runtime.context import RunContext
from aaosa.runtime.divider import TaskDivider
from aaosa.runtime.tagger import Tagger


def _ctx() -> RunContext:
    return RunContext(
        agents=[Agent(name="A", tags_with_elo={"python": 80}, system_prompt="x")],
        client=object(),
        divider=TaskDivider(system_prompt="d"),
        aggregator=TaskAggregator(system_prompt="a"),
        tagger=Tagger(system_prompt="t"),
    )


def test_runcontext_holds_dependencies():
    ctx = _ctx()
    assert ctx.tracer is None
    assert ctx.evaluator is None
    assert ctx.agents[0].name == "A"


def test_runcontext_is_frozen():
    ctx = _ctx()
    with pytest.raises(dataclasses.FrozenInstanceError):
        ctx.client = object()
