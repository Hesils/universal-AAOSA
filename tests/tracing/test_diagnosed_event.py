import pytest
from pydantic import TypeAdapter, ValidationError

from aaosa.tracing.events import ClaimEvent, DiagnosedEvent


def test_diagnosed_event_minimal():
    e = DiagnosedEvent(session_id="s", task_id="t", attribution="agent", reason="weak answer")
    assert e.type == "diagnosed"
    assert e.agent_id is None
    assert e.consignes is None


def test_diagnosed_event_full():
    e = DiagnosedEvent(
        session_id="s", task_id="t", agent_id="ag-1",
        attribution="evaluator", reason="criteria too strict", consignes="relax min_length",
    )
    assert e.attribution == "evaluator"
    assert e.consignes == "relax min_length"


def test_diagnosed_event_rejects_unknown_attribution():
    with pytest.raises(ValidationError):
        DiagnosedEvent(session_id="s", task_id="t", attribution="cosmic_rays", reason="r")


def test_diagnosed_event_roundtrip_through_union():
    e = DiagnosedEvent(session_id="s", task_id="t", agent_id="ag-1",
                       attribution="task_spec", reason="ambiguous")
    adapter = TypeAdapter(ClaimEvent)
    parsed = adapter.validate_json(e.model_dump_json())
    assert isinstance(parsed, DiagnosedEvent)
    assert parsed.attribution == "task_spec"


def test_diagnosed_event_forbids_extra():
    with pytest.raises(ValidationError):
        DiagnosedEvent(session_id="s", task_id="t", attribution="agent", reason="r", extra_field="x")
