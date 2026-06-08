from aaosa.tracing.events import UnassignedEvent
from aaosa.tracing.store import load_trace_partial
from aaosa.tracing.tracer import StreamingTracer, Tracer


def _ev(task_id: str) -> UnassignedEvent:
    return UnassignedEvent(session_id="s", task_id=task_id, reason="x")


def test_streaming_tracer_is_a_tracer():
    t = StreamingTracer(session_id="s", stream_path=None)
    assert isinstance(t, Tracer)


def test_emit_appends_line_readable_before_close(tmp_path):
    path = tmp_path / "trace.jsonl"
    t = StreamingTracer(session_id="s", stream_path=path)
    t.emit(_ev("t0"))
    # lisible MI-STREAM, avant close()/flush final
    events = load_trace_partial(path)
    assert [e.task_id for e in events] == ["t0"]
    t.emit(_ev("t1"))
    assert [e.task_id for e in load_trace_partial(path)] == ["t0", "t1"]
    t.close()


def test_emit_still_accumulates_in_memory(tmp_path):
    t = StreamingTracer(session_id="s", stream_path=tmp_path / "trace.jsonl")
    t.emit(_ev("t0"))
    t.emit(_ev("t1"))
    assert [e.task_id for e in t.events] == ["t0", "t1"]
    t.close()


def test_close_releases_handle_allows_rewrite(tmp_path):
    # après close(), un flush "w" sur le même fichier ne lève pas (lock Windows libéré)
    path = tmp_path / "trace.jsonl"
    t = StreamingTracer(session_id="s", stream_path=path)
    t.emit(_ev("t0"))
    t.close()
    t.flush(path)  # réécriture idempotente, ne doit pas lever
    assert [e.task_id for e in load_trace_partial(path)] == ["t0"]


def test_close_is_idempotent(tmp_path):
    t = StreamingTracer(session_id="s", stream_path=tmp_path / "trace.jsonl")
    t.close()
    t.close()  # second close ne lève pas
