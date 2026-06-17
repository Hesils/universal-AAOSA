# tests/runtime/test_manifest.py
from aaosa.runtime.manifest import build_manifest, Manifest
from aaosa.schemas.output import Output, LLMMetadata
from aaosa.claiming.dispatch import DispatchResult
from aaosa.tracing.events import ExecutedEvent, RosterGapEvent, ToolCalledEvent


def _executed(task_id="t1", agent_id="a1", content="answer"):
    return ExecutedEvent(session_id="s", task_id=task_id, agent_id=agent_id,
                         output_summary=content[:100], output_content=content)


def _tool(agent_id="a1", name="search", args=None, result="hit"):
    return ToolCalledEvent(session_id="s", task_id="t1", agent_id=agent_id,
                           tool_name=name, arguments=args or {"q": "x"}, result=result, latency_ms=1.0)


def test_manifest_from_successful_output():
    events = [_tool(), _executed()]
    result = Output(task_id="t1", agent_id="a1", content="answer", llm_metadata=LLMMetadata(model_name="test", tokens_in=1, tokens_out=1, latency_ms=1.0))
    m = build_manifest(events, result, "trace.jsonl")
    assert isinstance(m, Manifest)
    assert m.outcome == "success"
    assert m.typologies == ["simple"]
    assert [o.content for o in m.final_outputs] == ["answer"]
    assert m.tool_calls[0].tool_name == "search"
    assert m.trace_path == "trace.jsonl"
    assert m.roster_gaps == []


def test_manifest_roster_gap_is_surfaced_not_a_bug():
    events = [RosterGapEvent(session_id="s", task_id="t1", missing_tags=["forensics"])]
    result = DispatchResult(status="roster_gap", agent_id=None, reason="no agent")
    m = build_manifest(events, result, "trace.jsonl")
    assert m.outcome == "unassigned"
    assert m.roster_gaps == ["forensics"]
    assert m.final_outputs == []


def test_manifest_divided_run_takes_last_executed_as_final():
    events = [_executed(task_id="sub1", content="part1"), _executed(task_id="sub2", content="part2")]
    result = DispatchResult(status="unassigned", agent_id=None, reason="divided then merged elsewhere")
    # outcome unassigned mais un Output terminal existe dans la trace (run divisé court-circuité)
    m = build_manifest(events, result, "trace.jsonl")
    assert m.final_outputs[-1].content == "part2"
