from types import SimpleNamespace

import pytest

from aaosa.core.agent import Agent
from aaosa.runtime.context import RunContext
from aaosa.runtime.divider import DivisionResult, SubTaskSpec
from aaosa.runtime.runner import build_sub_tasks, _cross_role_unsatisfiable
from aaosa.schemas.task import Task


def _agent(name, tags):
    return Agent(name=name, tags_with_elo={t: 1500 for t in tags}, system_prompt="x")


_ROSTER = [
    _agent("python-dev", ["python", "coding"]),
    _agent("tech-writer", ["writing", "documentation"]),
]


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
