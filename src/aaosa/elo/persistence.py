from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from aaosa.core.agent import Agent


class AgentEloSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_name: str
    agent_id: str
    tags_with_elo: dict[str, int]


class EloSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timestamp: datetime
    agents: list[AgentEloSnapshot]


def save_snapshot(agents: list[Agent], directory: Path) -> Path:
    now = datetime.now(timezone.utc)
    snap = EloSnapshot(
        timestamp=now,
        agents=[
            AgentEloSnapshot(
                agent_name=a.name,
                agent_id=a.id,
                tags_with_elo=dict(a.tags_with_elo),
            )
            for a in agents
        ],
    )
    json_data = snap.model_dump_json(indent=2)

    ts_name = now.strftime("%Y-%m-%dT%H-%M-%S") + ".json"
    ts_path = directory / ts_name
    ts_path.write_text(json_data, encoding="utf-8")

    (directory / "latest.json").write_text(json_data, encoding="utf-8")

    return ts_path


def load_snapshot(path: Path) -> EloSnapshot:
    if not path.exists():
        raise FileNotFoundError(f"Snapshot not found: {path}")
    return EloSnapshot.model_validate_json(path.read_text(encoding="utf-8"))


def apply_snapshot(agents: list[Agent], snapshot: EloSnapshot) -> None:
    names = [a.name for a in agents]
    if len(names) != len(set(names)):
        raise ValueError(f"duplicate agent names in list: {[n for n in names if names.count(n) > 1]}")

    agent_by_name = {a.name: a for a in agents}
    for snap_agent in snapshot.agents:
        if snap_agent.agent_name in agent_by_name:
            agent_by_name[snap_agent.agent_name].tags_with_elo = dict(snap_agent.tags_with_elo)
