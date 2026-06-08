"""Détection pure de cycle/indices invalides sur un DivisionResult brut + section
de prompt cycle_context. Pas d'appel LLM : tout est mocké/pur."""

from aaosa.runtime.divider import (
    DivisionResult,
    SubTaskSpec,
    TaskDivider,
    find_cycle_indices,
)
from aaosa.schemas.task import Task


def _div(*deps: list[int]) -> DivisionResult:
    """Construit un DivisionResult à N sous-tâches, deps[i] = depends_on_indices de i."""
    return DivisionResult(
        is_atomic=False,
        sub_tasks=[SubTaskSpec(description=f"s{i}", depends_on_indices=d) for i, d in enumerate(deps)],
    )


class TestFindCycleIndices:
    def test_acyclic_returns_none(self):
        # 0 -> 1 -> 2 (linéaire, sain)
        assert find_cycle_indices(_div([], [0], [1])) is None

    def test_diamond_is_acyclic(self):
        # 0 ; 1<-0 ; 2<-0 ; 3<-1,2
        assert find_cycle_indices(_div([], [0], [0], [1, 2])) is None

    def test_self_reference_is_cycle(self):
        assert find_cycle_indices(_div([0])) == [0]

    def test_two_cycle(self):
        # 0 <-> 1
        result = find_cycle_indices(_div([1], [0]))
        assert result is not None
        assert set(result) == {0, 1}

    def test_three_cycle(self):
        # 0 -> 1 -> 2 -> 0
        result = find_cycle_indices(_div([2], [0], [1]))
        assert result is not None
        assert set(result) == {0, 1, 2}

    def test_out_of_bounds_index_flagged(self):
        # sous-tâche unique référant un indice inexistant
        result = find_cycle_indices(_div([5]))
        assert result is not None
        assert 0 in result

    def test_negative_index_flagged(self):
        result = find_cycle_indices(_div([-1]))
        assert result is not None
        assert 0 in result

    def test_atomic_division_returns_none(self):
        assert find_cycle_indices(DivisionResult(is_atomic=True)) is None

    def test_empty_deps_returns_none(self):
        assert find_cycle_indices(_div([], [], [])) is None


class TestCycleContextPrompt:
    def test_prompt_without_cycle_context_unchanged(self):
        divider = TaskDivider(system_prompt="sp")
        task = Task(description="ship it", required_tags={"python": 50})
        p = divider._build_divide_prompt(task, None, None, None)
        assert "cycle" not in p.lower()

    def test_prompt_includes_named_cycle_indices(self):
        divider = TaskDivider(system_prompt="sp")
        task = Task(description="ship it", required_tags={"python": 50})
        p = divider._build_divide_prompt(task, None, None, [0, 2])
        assert "cycle" in p.lower()
        # les indices fautifs sont nommés
        assert "0" in p and "2" in p

    def test_cycle_context_coexists_with_other_context(self):
        divider = TaskDivider(system_prompt="sp")
        task = Task(description="ship it", required_tags={"python": 50})
        ancestor = Task(description="root incident", required_tags={"backend": 70})
        p = divider._build_divide_prompt(task, [ancestor], None, [1])
        assert "root incident" in p
        assert "cycle" in p.lower()
