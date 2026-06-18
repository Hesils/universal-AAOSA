import pytest

from aaosa.runtime.runner import build_root_task, run_recovery
from aaosa.runtime.tagger import EmptyTaggingError
from aaosa.schemas.elo import DEFAULT_REQUIRED_ELO


class _FakeTagger:
    def __init__(self, tags):
        self._tags = set(tags)
    def tag(self, description, agents, provider, model=None):
        return self._tags


def _ctx(tagger):
    from aaosa.runtime.context import RunContext
    return RunContext(
        agents=[], provider=object(), divider=object(),
        aggregator=object(), tagger=tagger,
    )


def test_pinned_tags_skip_tagger_and_carry_context():
    ctx = _ctx(_FakeTagger([]))  # tagger must NOT be called
    task = build_root_task("do it", ctx, pinned_tags={"python": 1500}, context="ctx-here")
    assert task.required_tags == {"python": 1500}
    assert task.context == "ctx-here"


def test_tags_from_tagger_use_default_elo_and_carry_context():
    ctx = _ctx(_FakeTagger({"python"}))
    task = build_root_task("do it", ctx, context="provenance")
    assert task.required_tags == {"python": DEFAULT_REQUIRED_ELO}
    assert task.context == "provenance"


def test_empty_tagging_raises():
    ctx = _ctx(_FakeTagger(set()))
    with pytest.raises(EmptyTaggingError):
        build_root_task("do it", ctx)


def test_run_recovery_empty_tagging_returns_execution_failed():
    ctx = _ctx(_FakeTagger(set()))
    result = run_recovery("do it", ctx)
    from aaosa.claiming.dispatch import DispatchResult
    assert isinstance(result, DispatchResult)
    assert result.status == "execution_failed"
