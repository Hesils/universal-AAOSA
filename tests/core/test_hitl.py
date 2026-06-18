from aaosa.core.hitl import (
    ASK_HUMAN_TOOL_NAME,
    build_builtin_tools,
    make_ask_human_tool,
    unattended_callback,
)
from aaosa.core.tool import ToolDef


def test_unattended_callback_non_blocking_sentinel():
    out = unattended_callback("Where is the config?")
    assert isinstance(out, str)
    assert "No human" in out


def test_make_tool_captures_callback_in_closure():
    captured = {}

    def cb(question: str) -> str:
        captured["q"] = question
        return "the answer"

    tool = make_ask_human_tool(cb)
    assert isinstance(tool, ToolDef)
    assert tool.name == ASK_HUMAN_TOOL_NAME
    # fn signature is (**args) -> str ; called with the LLM-provided arg
    result = tool.fn(question="What is X?")
    assert result == "the answer"
    assert captured["q"] == "What is X?"


def test_make_tool_none_callback_uses_sentinel():
    tool = make_ask_human_tool(None)
    result = tool.fn(question="anything")
    assert result == unattended_callback("anything")


def test_tool_openai_schema_requires_question():
    tool = make_ask_human_tool(lambda q: "x")
    schema = tool.to_openai()
    params = schema["function"]["parameters"]
    assert params["required"] == ["question"]
    assert params["properties"]["question"]["type"] == "string"


def test_build_builtin_tools_maps_ask_human_by_name():
    cb = lambda q: "a"
    builtins = build_builtin_tools(cb)
    assert set(builtins) == {ASK_HUMAN_TOOL_NAME}
    assert builtins[ASK_HUMAN_TOOL_NAME].fn(question="q") == "a"


def test_build_builtin_tools_none_callback_still_present():
    builtins = build_builtin_tools(None)
    assert ASK_HUMAN_TOOL_NAME in builtins
    assert "No human" in builtins[ASK_HUMAN_TOOL_NAME].fn(question="q")
