from types import SimpleNamespace

import pytest

from aaosa.core.agent import Agent
from aaosa.runtime.context import RunContext
from aaosa.runtime.divider import DivisionResult, SubTaskSpec
from aaosa.runtime.runner import build_sub_tasks, _cross_role_unsatisfiable
from aaosa.runtime.tagger import UnsatisfiableTagSetError
from aaosa.schemas.task import Task
from aaosa.tracing.tracer import Tracer


def _agent(name, tags):
    return Agent(name=name, tags_with_elo={t: 1500 for t in tags}, system_prompt="x")


_ROSTER = [
    _agent("python-dev", ["python", "coding"]),
    _agent("tech-writer", ["writing", "documentation"]),
]


def _parent_task() -> Task:
    """Minimal parent Task pour les tests de build_sub_tasks."""
    return Task(description="parent task", required_tags={"python": 50})


def make_ctx(tagger=None) -> RunContext:
    """RunContext minimal : roster python-dev/tech-writer, divider/aggregator factices,
    tracer=None (les tests qui ont besoin d'un tracer espion le passent via le tagger)."""
    roster = [
        _agent("python-dev", ["python", "coding"]),
        _agent("tech-writer", ["writing", "documentation"]),
    ]
    return RunContext(
        agents=roster,
        provider=SimpleNamespace(),
        divider=SimpleNamespace(),
        aggregator=SimpleNamespace(),
        tagger=tagger if tagger is not None else _StubTagger(),
        tracer=None,
    )


class _ScriptedTagger:
    """1er appel (hint=None) → cross-rôle ; 2e appel (hint set) → `recovered`."""
    def __init__(self, first, recovered):
        self.first, self.recovered = first, recovered
        self.calls = []

    def tag(self, description, agents, provider, model=None, unsatisfiable_hint=None):
        self.calls.append(unsatisfiable_hint)
        return set(self.recovered) if unsatisfiable_hint else set(self.first)


def test_cross_role_subspec_is_retagged_single_role():
    # make_ctx : helper du fichier qui fabrique un RunContext avec roster python-dev/tech-writer
    tagger = _ScriptedTagger(
        first={"writing", "python", "coding", "documentation"},
        recovered={"python", "coding"},
    )
    ctx = make_ctx(tagger=tagger)
    parent = _parent_task()
    division = DivisionResult(is_atomic=False, sub_tasks=[
        SubTaskSpec(description="Write the helper validate_verdict"),
    ])
    subs = build_sub_tasks(parent, division, ctx)
    assert set(subs[0].required_tags) == {"python", "coding"}  # re-tagué single-rôle
    assert tagger.calls == [None, {"writing", "python", "coding", "documentation"}]  # 2 appels


def test_cross_role_unrecoverable_raises():
    tagger = _ScriptedTagger(
        first={"writing", "python", "coding", "documentation"},
        recovered={"writing", "python", "coding", "documentation"},  # re-tag reste cross-rôle
    )
    ctx = make_ctx(tagger=tagger)
    division = DivisionResult(is_atomic=False, sub_tasks=[
        SubTaskSpec(description="Write the helper"),
    ])
    with pytest.raises(UnsatisfiableTagSetError):
        build_sub_tasks(_parent_task(), division, ctx)


def test_cross_role_set_is_unsatisfiable():
    # couvert par l'union (python-dev + tech-writer) mais par aucun agent seul
    assert _cross_role_unsatisfiable({"writing", "python", "coding", "documentation"}, _ROSTER) is True


def test_single_role_subset_is_satisfiable():
    assert _cross_role_unsatisfiable({"python", "coding"}, _ROSTER) is False
    assert _cross_role_unsatisfiable({"writing", "documentation"}, _ROSTER) is False


def test_tag_absent_from_union_is_not_our_case():
    # 'rust' n'existe nulle part → roster_gap, pas cross-rôle
    assert _cross_role_unsatisfiable({"python", "rust"}, _ROSTER) is False


def test_single_agent_covering_all_is_satisfiable():
    fullstack = [_agent("fs", ["python", "coding", "writing", "documentation"])]
    assert _cross_role_unsatisfiable({"writing", "python", "coding", "documentation"}, fullstack) is False


class _StubTagger:
    def tag(self, description, agents, provider, model=None, unsatisfiable_hint=None):
        return {"python"}


def _ctx() -> RunContext:
    return RunContext(
        agents=[],
        provider=SimpleNamespace(),
        divider=SimpleNamespace(),
        aggregator=SimpleNamespace(),
        tagger=_StubTagger(),
        tracer=None,
    )


def test_cross_role_does_not_trigger_redivision():
    """La sous-spec 'Write…' cross-rôle est re-taguée single-rôle AU BUILD →
    elle ne reviendra jamais 'unassigned' → zéro re-division (verrou v24)."""
    tagger = _ScriptedTagger(
        first={"writing", "python", "coding", "documentation"},
        recovered={"python", "coding"},
    )
    ctx = make_ctx(tagger=tagger)
    division = DivisionResult(is_atomic=False, sub_tasks=[
        SubTaskSpec(description="Write the helper validate_verdict"),
    ])
    subs = build_sub_tasks(_parent_task(), division, ctx)
    assert subs[0].required_tags, "build_sub_tasks must produce non-empty required_tags"
    # single-rôle satisfiable → un agent unique (python-dev) couvre
    assert _cross_role_unsatisfiable(set(subs[0].required_tags), ctx.agents) is False


def test_build_sub_tasks_propagates_context():
    parent = Task(description="parent", required_tags={"python": 50})
    division = DivisionResult(sub_tasks=[
        SubTaskSpec(description="sub A", context="focalisé A"),
        SubTaskSpec(description="sub B"),  # context None
    ])
    subs = build_sub_tasks(parent, division, _ctx())
    assert subs[0].context == "focalisé A"
    assert subs[1].context is None
