from types import SimpleNamespace

from aaosa.runtime.aggregator import TaskAggregator
from aaosa.schemas.output import LLMMetadata, Output
from aaosa.schemas.task import Task
from aaosa.tracing.events import TaskAggregatedEvent
from aaosa.tracing.tracer import Tracer


def make_parent() -> Task:
    return Task(description="combine the pieces", required_tags={"python": 60})


def make_output(task_id="sub-1", content="piece") -> Output:
    return Output(
        task_id=task_id,
        agent_id="agent-x",
        content=content,
        llm_metadata=LLMMetadata(model_name="m", tokens_in=1, tokens_out=1, latency_ms=1.0),
    )


def _client(content="synthesized result"):
    def create(**kwargs):
        return SimpleNamespace(
            model="gpt-4o-mini",
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        )
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


class TestTaskAggregator:
    def test_aggregate_returns_output_with_parent_task_id(self):
        parent = make_parent()
        agg = TaskAggregator(system_prompt="You synthesize.")
        out = agg.aggregate(parent, [make_output()], _client())
        assert isinstance(out, Output)
        assert out.task_id == parent.id

    def test_aggregate_agent_id_is_sentinel(self):
        parent = make_parent()
        agg = TaskAggregator(system_prompt="You synthesize.")
        out = agg.aggregate(parent, [make_output()], _client())
        assert out.agent_id == "aggregator"

    def test_aggregate_emits_task_aggregated_event(self):
        parent = make_parent()
        tracer = Tracer(session_id="sess-1")
        agg = TaskAggregator(system_prompt="You synthesize.")
        out = agg.aggregate(
            parent,
            [make_output("sub-1"), make_output("sub-2")],
            _client("final answer"),
            tracer,
        )
        events = [e for e in tracer.events if isinstance(e, TaskAggregatedEvent)]
        assert len(events) == 1
        assert events[0].task_id == parent.id
        assert events[0].sub_task_ids == ["sub-1", "sub-2"]
        assert events[0].output_content == out.content

    def test_aggregate_llm_metadata_populated(self):
        parent = make_parent()
        agg = TaskAggregator(system_prompt="You synthesize.")
        out = agg.aggregate(parent, [make_output()], _client())
        assert out.llm_metadata is not None
        assert out.llm_metadata.tokens_in == 10
        assert out.llm_metadata.tokens_out == 5
