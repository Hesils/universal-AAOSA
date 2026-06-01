from pydantic import TypeAdapter

from aaosa.tracing.events import ClaimEvent, ToolCalledEvent


def make_event() -> ToolCalledEvent:
    return ToolCalledEvent(
        session_id="sess-1",
        task_id="t-1",
        agent_id="a-1",
        tool_name="search_docs",
        arguments={"query": "x"},
        result="found it",
        latency_ms=12.5,
    )


class TestToolCalledEvent:
    def test_tool_called_event_valid(self):
        ev = make_event()
        roundtrip = ToolCalledEvent.model_validate_json(ev.model_dump_json())
        assert roundtrip.tool_name == "search_docs"
        assert roundtrip.arguments == {"query": "x"}
        assert roundtrip.result == "found it"
        assert roundtrip.latency_ms == 12.5

    def test_tool_called_event_in_union(self):
        ev = make_event()
        adapter = TypeAdapter(ClaimEvent)
        parsed = adapter.validate_json(ev.model_dump_json())
        assert isinstance(parsed, ToolCalledEvent)
        assert parsed.type == "tool_called"
