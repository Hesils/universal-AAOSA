from types import SimpleNamespace

import pytest

from aaosa.core.agent import Agent
from aaosa.runtime.divider import (
    DivisionResult,
    SubTaskSpec,
    TagSpec,
    TaskDivider,
)
from aaosa.schemas.task import Task
from aaosa.tracing.events import TaskDividedEvent
from aaosa.tracing.tracer import Tracer


def make_agent(name="AgentA", elo=80) -> Agent:
    return Agent(
        name=name,
        tags_with_elo={"python": elo, "backend": elo},
        system_prompt=f"You are {name}.",
    )


def make_task(description="build a thing") -> Task:
    return Task(description=description, required_tags={"python": 60})


def _client_returning(division_result: DivisionResult):
    """Mock OpenAI client whose beta.chat.completions.parse returns division_result."""
    parsed = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(parsed=division_result))]
    )
    return SimpleNamespace(
        beta=SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(parse=lambda **kw: parsed)
            )
        )
    )


class TestTaskDivider:
    def test_divide_returns_subtasks_with_parent_id(self):
        task = make_task()
        result = DivisionResult(
            sub_tasks=[
                SubTaskSpec(description="step one", required_tags=[TagSpec(tag="python", elo=60)]),
                SubTaskSpec(description="step two", required_tags=[TagSpec(tag="backend", elo=60)]),
            ]
        )
        divider = TaskDivider(system_prompt="You split tasks.")
        sub_tasks = divider.divide(task, [make_agent()], _client_returning(result))

        assert len(sub_tasks) == 2
        assert all(st.parent_task_id == task.id for st in sub_tasks)
        assert sub_tasks[0].required_tags == {"python": 60}

    def test_divide_resolves_depends_on_indices(self):
        task = make_task()
        result = DivisionResult(
            sub_tasks=[
                SubTaskSpec(description="first", required_tags=[TagSpec(tag="python", elo=60)]),
                SubTaskSpec(
                    description="second",
                    required_tags=[TagSpec(tag="backend", elo=60)],
                    depends_on_indices=[0],
                ),
            ]
        )
        divider = TaskDivider(system_prompt="You split tasks.")
        sub_tasks = divider.divide(task, [make_agent()], _client_returning(result))

        assert sub_tasks[0].depends_on == []
        assert sub_tasks[1].depends_on == [sub_tasks[0].id]

    def test_divide_sets_order_index(self):
        task = make_task()
        result = DivisionResult(
            sub_tasks=[
                SubTaskSpec(description="a", required_tags=[TagSpec(tag="python", elo=60)]),
                SubTaskSpec(description="b", required_tags=[TagSpec(tag="python", elo=60)]),
                SubTaskSpec(description="c", required_tags=[TagSpec(tag="python", elo=60)]),
            ]
        )
        divider = TaskDivider(system_prompt="You split tasks.")
        sub_tasks = divider.divide(task, [make_agent()], _client_returning(result))

        assert [st.order_index for st in sub_tasks] == [0, 1, 2]

    def test_divide_emits_task_divided_event(self):
        task = make_task()
        result = DivisionResult(
            sub_tasks=[
                SubTaskSpec(description="a", required_tags=[TagSpec(tag="python", elo=60)]),
                SubTaskSpec(description="b", required_tags=[TagSpec(tag="python", elo=60)]),
            ]
        )
        tracer = Tracer(session_id="sess-1")
        divider = TaskDivider(system_prompt="You split tasks.")
        sub_tasks = divider.divide(task, [make_agent()], _client_returning(result), tracer)

        events = [e for e in tracer.events if isinstance(e, TaskDividedEvent)]
        assert len(events) == 1
        assert events[0].task_id == task.id
        assert events[0].sub_task_ids == [st.id for st in sub_tasks]

    def test_divide_requires_at_least_one_subtask(self):
        with pytest.raises(ValueError, match="sub_tasks cannot be empty"):
            DivisionResult(sub_tasks=[])
