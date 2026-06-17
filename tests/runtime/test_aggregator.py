"""Tests for TaskAggregator — uses provider.complete() (d6i migration)."""
from types import SimpleNamespace
from unittest.mock import MagicMock

from aaosa.runtime.aggregator import AGGREGATOR_AGENT_ID, TaskAggregator
from aaosa.runtime.providers import LLMProvider
from aaosa.schemas.output import LLMMetadata, Output
from aaosa.schemas.task import Task


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_task(desc: str = "diagnose the outage") -> Task:
    return Task(description=desc, required_tags={"backend": 80})


def _make_output(task_id: str, content: str) -> Output:
    return Output(
        task_id=task_id,
        agent_id="agent-x",
        content=content,
        llm_metadata=LLMMetadata(model_name="gpt-4o-mini", tokens_in=5, tokens_out=10, latency_ms=50.0),
    )


def _make_provider(content: str = "synthesized answer", model: str = "gpt-4o-mini",
                   tokens_in: int = 20, tokens_out: int = 30) -> MagicMock:
    """Build a provider mock whose .complete() returns a ChatCompletion-shaped response."""
    provider = MagicMock(spec=LLMProvider)
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        model=model,
        usage=SimpleNamespace(prompt_tokens=tokens_in, completion_tokens=tokens_out),
    )
    provider.complete.return_value = response
    return provider


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestTaskAggregator:
    def test_aggregate_returns_output_with_aggregator_sentinel(self):
        provider = _make_provider()
        task = _make_task()
        sub1 = _make_output(task.id, "result A")
        sub2 = _make_output(task.id, "result B")
        result = TaskAggregator(system_prompt="agg").aggregate(task, [sub1, sub2], provider)
        assert result.agent_id == AGGREGATOR_AGENT_ID

    def test_aggregate_output_task_id_matches_parent(self):
        provider = _make_provider()
        task = _make_task()
        sub = _make_output(task.id, "partial result")
        result = TaskAggregator(system_prompt="agg").aggregate(task, [sub], provider)
        assert result.task_id == task.id

    def test_aggregate_output_content_comes_from_llm(self):
        provider = _make_provider(content="final synthesis")
        task = _make_task()
        sub = _make_output(task.id, "part")
        result = TaskAggregator(system_prompt="agg").aggregate(task, [sub], provider)
        assert result.content == "final synthesis"

    def test_aggregate_llm_metadata_populated(self):
        provider = _make_provider(model="gpt-4o-mini", tokens_in=20, tokens_out=30)
        task = _make_task()
        sub = _make_output(task.id, "part")
        result = TaskAggregator(system_prompt="agg").aggregate(task, [sub], provider)
        assert result.llm_metadata.model_name == "gpt-4o-mini"
        assert result.llm_metadata.tokens_in == 20
        assert result.llm_metadata.tokens_out == 30
        assert result.llm_metadata.latency_ms > 0

    def test_aggregate_calls_complete_without_explicit_model(self):
        """Aggregator must NOT hardcode a model — provider default applies."""
        provider = _make_provider()
        task = _make_task()
        sub = _make_output(task.id, "part")
        TaskAggregator(system_prompt="agg").aggregate(task, [sub], provider)
        call_kwargs = provider.complete.call_args.kwargs
        assert "model" not in call_kwargs or call_kwargs.get("model") is None

    def test_aggregate_passes_task_description_in_user_message(self):
        provider = _make_provider()
        task = _make_task("find the root cause")
        sub = _make_output(task.id, "some result")
        TaskAggregator(system_prompt="agg").aggregate(task, [sub], provider)
        messages = provider.complete.call_args.kwargs["messages"]
        user_content = next(m["content"] for m in messages if m["role"] == "user")
        assert "find the root cause" in user_content

    def test_aggregate_passes_system_prompt_in_messages(self):
        provider = _make_provider()
        task = _make_task()
        sub = _make_output(task.id, "part")
        TaskAggregator(system_prompt="my-agg-prompt").aggregate(task, [sub], provider)
        messages = provider.complete.call_args.kwargs["messages"]
        sys_content = next(m["content"] for m in messages if m["role"] == "system")
        assert sys_content == "my-agg-prompt"

    def test_aggregate_emits_event_when_tracer_provided(self):
        from unittest.mock import patch
        provider = _make_provider()
        task = _make_task()
        sub = _make_output(task.id, "part")
        tracer = MagicMock()
        tracer.session_id = "sess-1"
        result = TaskAggregator(system_prompt="agg").aggregate(task, [sub], provider, tracer=tracer)
        tracer.emit.assert_called_once()

    def test_aggregate_no_tracer_does_not_raise(self):
        provider = _make_provider()
        task = _make_task()
        sub = _make_output(task.id, "part")
        # Must not raise when tracer=None (default)
        result = TaskAggregator(system_prompt="agg").aggregate(task, [sub], provider)
        assert result is not None
