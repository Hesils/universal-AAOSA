import uuid
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from aaosa.core.agent import Agent


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
