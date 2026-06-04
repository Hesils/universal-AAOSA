from types import SimpleNamespace
from unittest.mock import patch

from aaosa.claiming.dispatch import DispatchResult
from aaosa.core.agent import Agent
from aaosa.runtime.aggregator import TaskAggregator
from aaosa.runtime.divider import DivisionResult, SubTaskSpec, TagSpec, TaskDivider
from aaosa.runtime.runner import run_divided_task
from aaosa.schemas.output import LLMMetadata, Output
from aaosa.schemas.task import Task
from aaosa.tracing.events import (
    ExecutedEvent,
    TaskAggregatedEvent,
    TaskDividedEvent,
)
from aaosa.tracing.tracer import Tracer


def make_agent() -> Agent:
    return Agent(name="A", tags_with_elo={"python": 80}, system_prompt="You are A.")


def make_task() -> Task:
    return Task(description="big task", required_tags={"python": 60})


def make_output(task_id="sub", content="c") -> Output:
    return Output(
        task_id=task_id,
        agent_id="x",
        content=content,
        llm_metadata=LLMMetadata(model_name="m", tokens_in=1, tokens_out=1, latency_ms=1.0),
    )


def _divider_client():
    result = DivisionResult(
        sub_tasks=[
            SubTaskSpec(description="s1", required_tags=[TagSpec(tag="python", elo=60)]),
            SubTaskSpec(description="s2", required_tags=[TagSpec(tag="python", elo=60)]),
        ]
    )
    parsed = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(parsed=result))])
    return SimpleNamespace(
        beta=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(parse=lambda **kw: parsed)))
    )


def _aggregator_client(content="final"):
    def create(**kwargs):
        return SimpleNamespace(
            model="gpt-4o-mini",
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
        )
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


class _FakeDivider:
    def divide(self, task, agents, client, tracer=None):
        return [
            Task(description="s1", required_tags={"python": 60}, parent_task_id=task.id, order_index=0),
            Task(description="s2", required_tags={"python": 60}, parent_task_id=task.id, order_index=1),
        ]


class _RecordingAggregator:
    def __init__(self):
        self.received = None

    def aggregate(self, parent_task, sub_outputs, client, tracer=None):
        self.received = list(sub_outputs)
        return make_output(parent_task.id, "agg")


class _ExplodingAggregator:
    def aggregate(self, parent_task, sub_outputs, client, tracer=None):
        raise RuntimeError("LLM exploded")


class _ExplodingDivider:
    def divide(self, task, agents, client, tracer=None):
        raise RuntimeError("divider LLM exploded")


class TestRunDividedTask:
    def test_run_divided_task_returns_output(self):
        task = make_task()
        agg = _RecordingAggregator()
        with patch("aaosa.runtime.runner.run_chain", return_value=[make_output("s1"), make_output("s2")]):
            result = run_divided_task(task, [make_agent()], object(), _FakeDivider(), agg)
        assert isinstance(result, Output)
        assert result.content == "agg"

    def test_run_divided_task_no_successful_subtasks(self):
        task = make_task()
        dispatch_fail = DispatchResult(status="unassigned", agent_id=None, reason="no claim")
        with patch("aaosa.runtime.runner.run_chain", return_value=[dispatch_fail, dispatch_fail]):
            result = run_divided_task(task, [make_agent()], object(), _FakeDivider(), _RecordingAggregator())
        assert isinstance(result, DispatchResult)
        assert result.status == "unassigned"

    def test_run_divided_task_aggregates_only_successful(self):
        task = make_task()
        dispatch_fail = DispatchResult(status="unassigned", agent_id=None, reason="no claim")
        agg = _RecordingAggregator()
        with patch("aaosa.runtime.runner.run_chain", return_value=[make_output("s1"), dispatch_fail]):
            run_divided_task(task, [make_agent()], object(), _FakeDivider(), agg)
        assert len(agg.received) == 1
        assert agg.received[0].task_id == "s1"

    def test_run_divided_task_fallback_on_aggregator_exception(self):
        task = make_task()
        with patch("aaosa.runtime.runner.run_chain", return_value=[make_output("s1"), make_output("s2")]):
            result = run_divided_task(task, [make_agent()], object(), _FakeDivider(), _ExplodingAggregator())
        assert isinstance(result, Output)
        assert result.task_id == "s2"  # last successful output (fallback C)

    def test_run_divided_task_divide_raises_falls_back_to_simple_run(self):
        """divide() qui lève -> run_divided_task retombe sur un run simple
        (run_task sur la tâche d'origine) au lieu de tuer le run (Gap 1)."""
        task = make_task()
        sentinel = make_output(task.id, "simple-run-result")
        with patch("aaosa.runtime.runner.run_task", return_value=sentinel) as rt:
            with patch("aaosa.runtime.runner.run_chain") as rc:
                result = run_divided_task(task, [make_agent()], object(), _ExplodingDivider(), _RecordingAggregator())
        assert result is sentinel
        rc.assert_not_called()
        rt.assert_called_once()
        assert rt.call_args.args[0] is task

    def test_run_divided_task_tracer_event_order(self):
        task = make_task()
        tracer = Tracer(session_id="sess-1")
        divider = TaskDivider(system_prompt="split")
        aggregator = TaskAggregator(system_prompt="merge")

        def fake_run_chain(tasks, agents, client, tr=None, evaluator=None):
            # emit a sub-task event so we can assert ordering
            tr.emit(ExecutedEvent(
                session_id=tr.session_id, task_id=tasks[0].id, agent_id="x",
                output_summary="s", output_content="s",
            ))
            return [make_output(t.id) for t in tasks]

        # divide() uses a structured-output client; aggregate() uses a chat client.
        # run_divided_task passes a single client to both — give it both shapes.
        client = SimpleNamespace(
            beta=_divider_client().beta,
            chat=_aggregator_client().chat,
        )
        with patch("aaosa.runtime.runner.run_chain", side_effect=fake_run_chain):
            run_divided_task(task, [make_agent()], client, divider, aggregator, tracer)

        types = [type(e) for e in tracer.events]
        assert types[0] is TaskDividedEvent
        assert types[-1] is TaskAggregatedEvent
        assert ExecutedEvent in types
        assert types.index(TaskDividedEvent) < types.index(ExecutedEvent) < types.index(TaskAggregatedEvent)
