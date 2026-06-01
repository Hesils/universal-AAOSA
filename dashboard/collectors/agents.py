from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from aaosa.elo.persistence import EloSnapshot
from aaosa.tracing.events import DispatchedEvent, Phase2ClaimedEvent, QAEvaluatedEvent
from aaosa.tracing.store import AgentRegistry, load_trace


class AgentListItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str
    name: str
    tags_with_elo: dict[str, int]


class AgentList(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agents: list[AgentListItem]


class EloPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timestamp: datetime
    elo: int


class TagEloSeries(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tag: str
    points: list[EloPoint]


class AgentActivity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claims: int
    wins: int
    successes: int
    failures: int


class AgentDetailView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str
    name: str
    system_prompt: str
    tags_with_elo: dict[str, int]
    elo_history: list[TagEloSeries]
    activity: AgentActivity


def _load_registry(runs_root: Path) -> AgentRegistry | None:
    path = runs_root / "agents" / "registry.json"
    if not path.exists():
        return None
    return AgentRegistry.model_validate_json(path.read_text(encoding="utf-8"))


def list_agents(runs_root: Path) -> AgentList:
    reg = _load_registry(runs_root)
    if reg is None:
        return AgentList(agents=[])
    return AgentList(agents=[
        AgentListItem(agent_id=e.agent_id, name=e.name, tags_with_elo=e.tags_with_elo)
        for e in reg.agents
    ])


def _elo_history(runs_root: Path, agent_name: str) -> list[TagEloSeries]:
    snap_dir = runs_root / "elo_snapshots"
    if not snap_dir.exists():
        return []
    series: dict[str, list[EloPoint]] = {}
    for f in sorted(snap_dir.glob("*.json")):
        if f.name == "latest.json":
            continue
        snap = EloSnapshot.model_validate_json(f.read_text(encoding="utf-8"))
        for a in snap.agents:
            if a.agent_name != agent_name:  # nom stable, pas l'UUID régénéré (invariant projet)
                continue
            for tag, elo in a.tags_with_elo.items():
                series.setdefault(tag, []).append(EloPoint(timestamp=snap.timestamp, elo=elo))
    return [TagEloSeries(tag=tag, points=pts) for tag, pts in sorted(series.items())]


def _activity(runs_root: Path, agent_id: str) -> AgentActivity:
    claims = wins = successes = failures = 0
    sdir = runs_root / "sessions"
    if sdir.exists():
        for d in sorted(sdir.iterdir()):
            trace = d / "trace.jsonl"
            if not trace.exists():
                continue
            for e in load_trace(trace):
                if isinstance(e, Phase2ClaimedEvent) and e.agent_id == agent_id and e.decision == "claim":
                    claims += 1
                elif isinstance(e, DispatchedEvent) and e.agent_id == agent_id:
                    wins += 1
                elif isinstance(e, QAEvaluatedEvent) and e.agent_id == agent_id:
                    if e.success:
                        successes += 1
                    else:
                        failures += 1
    return AgentActivity(claims=claims, wins=wins, successes=successes, failures=failures)


def agent_detail(runs_root: Path, agent_id: str) -> AgentDetailView | None:
    reg = _load_registry(runs_root)
    if reg is None:
        return None
    entry = next((e for e in reg.agents if e.agent_id == agent_id), None)
    if entry is None:
        return None
    return AgentDetailView(
        agent_id=entry.agent_id,
        name=entry.name,
        system_prompt=entry.system_prompt,
        tags_with_elo=entry.tags_with_elo,
        elo_history=_elo_history(runs_root, entry.name),
        activity=_activity(runs_root, agent_id),
    )
