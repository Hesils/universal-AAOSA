import json
from types import SimpleNamespace

from aaosa.core.agent import Agent
from aaosa.core.hitl import make_ask_human_tool
from aaosa.schemas.task import Task
from aaosa.tracing.events import ToolCalledEvent
from aaosa.tracing.tracer import Tracer


def _resp(finish_reason, content=None, tool_calls=None, tin=5, tout=3):
    msg = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(finish_reason=finish_reason, message=msg)
    return SimpleNamespace(
        model="gpt-4o-mini",
        choices=[choice],
        usage=SimpleNamespace(prompt_tokens=tin, completion_tokens=tout),
    )


def _tool_call(name, args_dict, call_id="call_1"):
    return SimpleNamespace(
        id=call_id, function=SimpleNamespace(name=name, arguments=json.dumps(args_dict))
    )


def _queue_provider(responses):
    it = iter(responses)

    def complete(*, messages, model=None, tools=None, **kwargs):
        return next(it)

    return SimpleNamespace(complete=complete)


def test_ask_human_round_trips_through_execute_and_traces():
    captured = {}

    def cb(question: str) -> str:
        captured["q"] = question
        return "use config.yaml"

    agent = Agent(
        name="A",
        tags_with_elo={"python": 80},
        system_prompt="You are A.",
        tools=[make_ask_human_tool(cb)],
    )
    task = Task(description="do it", required_tags={"python": 60})
    provider = _queue_provider([
        _resp("tool_calls", tool_calls=[_tool_call("ask_human", {"question": "Which config?"})]),
        _resp("stop", content="done with config.yaml"),
    ])
    tracer = Tracer(session_id="sess-hitl")

    out = agent.execute(task, provider, tracer)

    assert out.content == "done with config.yaml"
    assert out.llm_metadata.tool_calls_count == 1
    assert captured["q"] == "Which config?"
    hitl_events = [e for e in tracer.events if isinstance(e, ToolCalledEvent) and e.tool_name == "ask_human"]
    assert len(hitl_events) == 1
    assert hitl_events[0].arguments == {"question": "Which config?"}
    assert hitl_events[0].result == "use config.yaml"
