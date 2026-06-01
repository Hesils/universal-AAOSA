import json
from types import SimpleNamespace

import pytest

from aaosa.core.agent import Agent
from aaosa.core.tool import MAX_TOOL_ROUNDS, ToolDef
from aaosa.schemas.output import Output
from aaosa.schemas.task import Task
from aaosa.tracing.events import ToolCalledEvent
from aaosa.tracing.tracer import Tracer


def echo(query: str) -> str:
    return f"echoed:{query}"


def make_tool() -> ToolDef:
    return ToolDef(
        name="echo",
        description="Echo the query",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        fn=echo,
    )


def make_agent(tools=None) -> Agent:
    return Agent(
        name="A",
        tags_with_elo={"python": 80},
        system_prompt="You are A.",
        tools=tools or [],
    )


def make_task() -> Task:
    return Task(description="do it", required_tags={"python": 60})


def _resp(finish_reason, content=None, tool_calls=None, tin=5, tout=3):
    msg = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(finish_reason=finish_reason, message=msg)
    return SimpleNamespace(
        model="gpt-4o-mini",
        choices=[choice],
        usage=SimpleNamespace(prompt_tokens=tin, completion_tokens=tout),
    )


def _tool_call(name, args_dict, call_id="call_1"):
    return SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=json.dumps(args_dict)))


def _queue_client(responses):
    it = iter(responses)
    captured = {"calls": []}

    def create(**kwargs):
        captured["calls"].append(kwargs)
        return next(it)

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return client, captured


def _always_tool_call_client():
    def create(**kwargs):
        return _resp("tool_calls", tool_calls=[_tool_call("echo", {"query": "loop"})])

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


class TestExecuteWithTools:
    def test_execute_no_tools_unchanged(self):
        client, _ = _queue_client([_resp("stop", content="answer")])
        out = make_agent().execute(make_task(), client)
        assert isinstance(out, Output)
        assert out.content == "answer"
        assert out.llm_metadata.tool_calls_count == 0

    def test_execute_tools_llm_stops_immediately(self):
        client, captured = _queue_client([_resp("stop", content="direct answer")])
        out = make_agent(tools=[make_tool()]).execute(make_task(), client)
        assert out.content == "direct answer"
        assert out.llm_metadata.tool_calls_count == 0
        # tools were offered to the API
        assert "tools" in captured["calls"][0]

    def test_execute_tools_one_tool_call(self):
        responses = [
            _resp("tool_calls", tool_calls=[_tool_call("echo", {"query": "hi"})]),
            _resp("stop", content="final answer"),
        ]
        client, _ = _queue_client(responses)
        out = make_agent(tools=[make_tool()]).execute(make_task(), client)
        assert out.content == "final answer"
        assert out.llm_metadata.tool_calls_count == 1

    def test_execute_tools_aggregates_tokens(self):
        responses = [
            _resp("tool_calls", tool_calls=[_tool_call("echo", {"query": "hi"})], tin=5, tout=3),
            _resp("stop", content="done", tin=7, tout=2),
        ]
        client, _ = _queue_client(responses)
        out = make_agent(tools=[make_tool()]).execute(make_task(), client)
        assert out.llm_metadata.tokens_in == 12
        assert out.llm_metadata.tokens_out == 5

    def test_execute_tools_emits_tool_called_event(self):
        responses = [
            _resp("tool_calls", tool_calls=[_tool_call("echo", {"query": "hi"})]),
            _resp("stop", content="final"),
        ]
        client, _ = _queue_client(responses)
        tracer = Tracer(session_id="sess-1")
        agent = make_agent(tools=[make_tool()])
        agent.execute(make_task(), client, tracer)
        events = [e for e in tracer.events if isinstance(e, ToolCalledEvent)]
        assert len(events) == 1
        assert events[0].tool_name == "echo"
        assert events[0].arguments == {"query": "hi"}
        assert events[0].result == "echoed:hi"
        assert events[0].agent_id == agent.id

    def test_execute_max_rounds_raises(self):
        client = _always_tool_call_client()
        with pytest.raises(RuntimeError, match="Max tool rounds"):
            make_agent(tools=[make_tool()]).execute(make_task(), client)

    def test_execute_treats_length_as_terminal(self):
        client, _ = _queue_client([_resp("length", content="truncated")])
        out = make_agent(tools=[make_tool()]).execute(make_task(), client)
        assert out.content == "truncated"
        assert out.llm_metadata.tool_calls_count == 0
