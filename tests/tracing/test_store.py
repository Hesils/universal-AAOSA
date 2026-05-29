from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from aaosa.core.agent import Agent
from aaosa.tracing.events import ClaimEvent, ExecutedEvent
from aaosa.tracing.store import (
    AgentRegistry,
    AgentRegistryEntry,
    SessionMeta,
    SessionTaskRecord,
    new_session_id,
    save_agent_registry,
    save_session,
)
from aaosa.tracing.tracer import Tracer


def make_agent(name: str, tags: dict[str, int]) -> Agent:
    return Agent(name=name, tags_with_elo=tags, system_prompt=f"prompt for {name}")


class TestNewSessionId:
    def test_is_unique(self):
        ids = {new_session_id() for _ in range(50)}
        assert len(ids) == 50

    def test_is_sortable_string(self):
        sid = new_session_id()
        assert isinstance(sid, str)
        # forme: 2026-05-29T14-30-00-ab12
        assert sid[:4].isdigit()
        assert "T" in sid


class TestSaveAgentRegistry:
    def test_writes_file(self, tmp_path):
        agents = [make_agent("Frontend", {"css": 80})]
        path = save_agent_registry(agents, tmp_path / "agents" / "registry.json")
        assert path.exists()

    def test_creates_parent_dirs(self, tmp_path):
        agents = [make_agent("Frontend", {"css": 80})]
        save_agent_registry(agents, tmp_path / "agents" / "registry.json")
        assert (tmp_path / "agents").is_dir()

    def test_roundtrip(self, tmp_path):
        agents = [
            make_agent("Frontend", {"css": 80, "javascript": 70}),
            make_agent("Backend", {"python": 90}),
        ]
        path = save_agent_registry(agents, tmp_path / "registry.json")
        reg = AgentRegistry.model_validate_json(path.read_text(encoding="utf-8"))
        assert len(reg.agents) == 2
        fe = next(e for e in reg.agents if e.name == "Frontend")
        assert fe.tags_with_elo == {"css": 80, "javascript": 70}
        assert fe.system_prompt == "prompt for Frontend"
        assert fe.agent_id == agents[0].id

    def test_entry_rejects_extra_field(self):
        with pytest.raises(Exception):
            AgentRegistryEntry(
                agent_id="1", name="X", system_prompt="p",
                tags_with_elo={"a": 1}, bogus="bad",
            )


def make_meta(session_id: str) -> SessionMeta:
    now = datetime.now(timezone.utc)
    return SessionMeta(
        session_id=session_id,
        started_at=now,
        ended_at=now,
        tasks=[
            SessionTaskRecord(
                id="t1", description="do a thing",
                winner_agent_id="a1", outcome="qa_pass",
                required_tags={"python": 50},
            ),
            SessionTaskRecord(
                id="t2", description="impossible",
                winner_agent_id=None, outcome="unassigned",
                required_tags={"rust": 90},
            ),
        ],
        agent_ids=["a1", "a2"],
    )


class TestSessionTaskRecord:
    def test_outcome_rejects_unknown_value(self):
        with pytest.raises(Exception):
            SessionTaskRecord(
                id="t1", description="x",
                winner_agent_id="a1", outcome="weird",
            )

    def test_unassigned_allows_none_winner(self):
        rec = SessionTaskRecord(
            id="t1", description="x", winner_agent_id=None, outcome="unassigned",
            required_tags={"python": 50},
        )
        assert rec.winner_agent_id is None

    def test_required_tags_stored(self):
        rec = SessionTaskRecord(
            id="t1", description="x", winner_agent_id="a1",
            outcome="qa_pass", required_tags={"python": 50, "sql": 30},
        )
        assert rec.required_tags == {"python": 50, "sql": 30}

    def test_required_tags_is_required(self):
        with pytest.raises(Exception):
            SessionTaskRecord(
                id="t1", description="x", winner_agent_id="a1", outcome="qa_pass",
            )


class TestSaveSession:
    def test_writes_trace_and_meta(self, tmp_path):
        tracer = Tracer(session_id="2026-05-29T10-00-00-ab12")
        tracer.emit(ExecutedEvent(
            session_id=tracer.session_id, task_id="t1",
            agent_id="a1", output_summary="done",
        ))
        meta = make_meta(tracer.session_id)
        session_dir = save_session(tracer, meta, tmp_path)
        assert (session_dir / "trace.jsonl").exists()
        assert (session_dir / "meta.json").exists()

    def test_session_dir_path(self, tmp_path):
        tracer = Tracer(session_id="2026-05-29T10-00-00-ab12")
        meta = make_meta(tracer.session_id)
        session_dir = save_session(tracer, meta, tmp_path)
        assert session_dir == tmp_path / "sessions" / "2026-05-29T10-00-00-ab12"

    def test_meta_roundtrip(self, tmp_path):
        tracer = Tracer(session_id="2026-05-29T10-00-00-ab12")
        meta = make_meta(tracer.session_id)
        session_dir = save_session(tracer, meta, tmp_path)
        loaded = SessionMeta.model_validate_json(
            (session_dir / "meta.json").read_text(encoding="utf-8")
        )
        assert loaded.session_id == meta.session_id
        assert len(loaded.tasks) == 2
        assert loaded.tasks[1].outcome == "unassigned"
        assert loaded.agent_ids == ["a1", "a2"]
        assert loaded.tasks[0].required_tags == {"python": 50}

    def test_trace_roundtrip(self, tmp_path):
        tracer = Tracer(session_id="2026-05-29T10-00-00-ab12")
        tracer.emit(ExecutedEvent(
            session_id=tracer.session_id, task_id="t1",
            agent_id="a1", output_summary="done",
        ))
        meta = make_meta(tracer.session_id)
        session_dir = save_session(tracer, meta, tmp_path)
        adapter = TypeAdapter(ClaimEvent)
        lines = (session_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        events = [adapter.validate_json(line) for line in lines if line.strip()]
        assert len(events) == 1
        assert isinstance(events[0], ExecutedEvent)

    def test_session_id_mismatch_raises(self, tmp_path):
        tracer = Tracer(session_id="sid-A")
        meta = make_meta("sid-B")
        with pytest.raises(ValueError, match="session_id"):
            save_session(tracer, meta, tmp_path)
