import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from aaosa.core.agent import Agent
from aaosa.tracing.tracer import Tracer


def new_session_id() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H-%M-%S") + "-" + uuid.uuid4().hex[:4]


class AgentRegistryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str
    name: str
    system_prompt: str
    tags_with_elo: dict[str, int]


class AgentRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agents: list[AgentRegistryEntry]


def save_agent_registry(agents: list[Agent], path: Path) -> Path:
    registry = AgentRegistry(
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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(registry.model_dump_json(indent=2), encoding="utf-8")
    return path


TaskOutcome = Literal["qa_pass", "qa_fail", "unassigned", "no_qa"]


class SessionTaskRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    description: str
    winner_agent_id: str | None
    outcome: TaskOutcome


class SessionMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str
    started_at: datetime
    ended_at: datetime
    tasks: list[SessionTaskRecord]
    agent_ids: list[str]


def save_session(tracer: Tracer, meta: SessionMeta, runs_root: Path) -> Path:
    if tracer.session_id != meta.session_id:
        raise ValueError(
            f"tracer.session_id ({tracer.session_id!r}) != meta.session_id ({meta.session_id!r})"
        )
    session_dir = runs_root / "sessions" / meta.session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    tracer.flush(session_dir / "trace.jsonl")
    (session_dir / "meta.json").write_text(meta.model_dump_json(indent=2), encoding="utf-8")
    return session_dir
