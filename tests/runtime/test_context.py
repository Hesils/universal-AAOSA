import dataclasses
from dataclasses import replace
from types import SimpleNamespace

import pytest

from aaosa.core.agent import Agent
from aaosa.runtime.aggregator import TaskAggregator
from aaosa.runtime.context import RunContext
from aaosa.runtime.divider import TaskDivider
from aaosa.runtime.tagger import Tagger


def _ctx() -> RunContext:
    return RunContext(
        agents=[Agent(name="A", tags_with_elo={"python": 80}, system_prompt="x")],
        provider=object(),
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
        ctx.provider = object()


def _minimal_ctx(**over):
    """Réutilise les fakes du fichier si présents ; sinon SimpleNamespace suffit
    car RunContext ne valide pas ses membres (dataclass, pas Pydantic)."""
    base = dict(
        agents=[],
        provider=SimpleNamespace(),
        divider=SimpleNamespace(),
        aggregator=SimpleNamespace(),
        tagger=SimpleNamespace(),
    )
    base.update(over)
    return RunContext(**base)


def test_runcontext_hitl_callback_defaults_none():
    ctx = _minimal_ctx()
    assert ctx.hitl_callback is None


def test_runcontext_hitl_callback_preserved_by_replace():
    cb = lambda q: "a"
    ctx = _minimal_ctx(hitl_callback=cb)
    ctx2 = replace(ctx, tracer=SimpleNamespace())
    assert ctx2.hitl_callback is cb
