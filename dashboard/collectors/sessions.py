from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from aaosa.tracing.store import AgentRegistry, AgentRegistryEntry, SessionMeta, load_trace_partial
from dashboard.graph_model import GraphModel, build_graph


class SessionListItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str
    started_at: datetime
    ended_at: datetime
    task_count: int
    agent_count: int
    status: str


class SessionList(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sessions: list[SessionListItem]


class SessionView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    meta: SessionMeta
    agents: list[AgentRegistryEntry]
    graph: GraphModel


def _sessions_dir(runs_root: Path) -> Path:
    return runs_root / "sessions"


def _load_meta(session_dir: Path) -> SessionMeta:
    return SessionMeta.model_validate_json((session_dir / "meta.json").read_text(encoding="utf-8"))


def _load_agents(session_dir: Path) -> list[AgentRegistryEntry]:
    path = session_dir / "agents.json"
    if not path.exists():
        return []
    return AgentRegistry.model_validate_json(path.read_text(encoding="utf-8")).agents


def list_sessions(runs_root: Path) -> SessionList:
    sdir = _sessions_dir(runs_root)
    items: list[SessionListItem] = []
    if sdir.exists():
        for d in sorted(sdir.iterdir()):
            if not (d / "meta.json").exists():
                continue
            meta = _load_meta(d)
            items.append(SessionListItem(
                session_id=meta.session_id,
                started_at=meta.started_at,
                ended_at=meta.ended_at,
                task_count=len(meta.tasks),
                agent_count=len(meta.agent_ids),
                status=meta.status,
            ))
    items.sort(key=lambda s: s.started_at, reverse=True)
    return SessionList(sessions=items)


def session_status(runs_root: Path, session_id: str) -> str | None:
    """Statut d'une session ("running"/"complete") sans charger la trace ni
    construire le graphe. None si la session (ou son meta.json) n'existe pas."""
    d = _sessions_dir(runs_root) / session_id
    if not (d / "meta.json").exists():
        return None
    return _load_meta(d).status


def session_detail(runs_root: Path, session_id: str) -> SessionView | None:
    d = _sessions_dir(runs_root) / session_id
    if not (d / "meta.json").exists() or not (d / "trace.jsonl").exists():
        return None
    meta = _load_meta(d)
    graph = build_graph(load_trace_partial(d / "trace.jsonl"), meta)
    return SessionView(meta=meta, agents=_load_agents(d), graph=graph)
