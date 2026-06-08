import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, TypeAdapter

from aaosa.core.agent import Agent
from aaosa.tracing.events import ClaimEvent
from aaosa.tracing.tracer import Tracer

_event_adapter = TypeAdapter(ClaimEvent)


def new_session_id() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H-%M-%S") + "-" + uuid.uuid4().hex[:8]


class AgentRegistryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str
    name: str
    system_prompt: str
    tags_with_elo: dict[str, int]


class AgentRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agents: list[AgentRegistryEntry]


def _build_registry(agents: list[Agent]) -> AgentRegistry:
    return AgentRegistry(
        agents=[
            AgentRegistryEntry(
                agent_id=a.id,
                name=a.name,
                system_prompt=a.system_prompt,
                tags_with_elo=dict(a.tags_with_elo),
            )
            for a in agents
        ]
    )


def save_agent_registry(agents: list[Agent], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_build_registry(agents).model_dump_json(indent=2), encoding="utf-8")
    return path


TaskOutcome = Literal["qa_pass", "qa_fail", "unassigned", "no_qa", "divided"]


class SessionTaskRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    description: str
    winner_agent_id: str | None
    outcome: TaskOutcome
    required_tags: dict[str, int]
    context: str | None = None


class SessionMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str
    started_at: datetime
    ended_at: datetime
    tasks: list[SessionTaskRecord]
    agent_ids: list[str]
    status: Literal["running", "complete"] = "complete"


def save_session(
    tracer: Tracer,
    meta: SessionMeta,
    runs_root: Path,
    agents: list[Agent] | None = None,
) -> Path:
    if tracer.session_id != meta.session_id:
        raise ValueError(
            f"tracer.session_id ({tracer.session_id!r}) != meta.session_id ({meta.session_id!r})"
        )
    session_dir = runs_root / "sessions" / meta.session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    tracer.flush(session_dir / "trace.jsonl")
    (session_dir / "meta.json").write_text(meta.model_dump_json(indent=2), encoding="utf-8")
    if agents is not None:
        (session_dir / "agents.json").write_text(
            _build_registry(agents).model_dump_json(indent=2), encoding="utf-8"
        )
    return session_dir


def load_trace(path: Path) -> list[ClaimEvent]:
    """Lit un trace.jsonl en liste d'events. Inverse de Tracer.flush."""
    return [
        _event_adapter.validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
