from flask import Blueprint, current_app
from pydantic import BaseModel, ConfigDict

from aaosa.tracing.store import AgentRegistryEntry, SessionMeta
from dashboard.collectors import agents as agents_collector
from dashboard.collectors import infra as infra_collector
from dashboard.collectors import sessions as sessions_collector
from dashboard.serialization import error_response, json_response

api = Blueprint("api", __name__, url_prefix="/api")


def _runs_root():
    return current_app.config["AAOSA"].runs_root


def _cache():
    return current_app.config["CACHE"]


@api.get("/infra")
def get_infra():
    return json_response(infra_collector.collect(_runs_root()))


@api.get("/agents")
def get_agents():
    return json_response(agents_collector.list_agents(_runs_root()))


@api.get("/agents/<agent_id>")
def get_agent(agent_id):
    view = _cache().get_or_compute(
        f"agent:{agent_id}", lambda: agents_collector.agent_detail(_runs_root(), agent_id)
    )
    if view is None:
        return error_response(f"agent {agent_id} not found")
    return json_response(view)


class SessionDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    meta: SessionMeta
    agents: list[AgentRegistryEntry]


def _session_view(session_id):
    return _cache().get_or_compute(
        f"session_view:{session_id}",
        lambda: sessions_collector.session_detail(_runs_root(), session_id),
    )


@api.get("/sessions")
def get_sessions():
    return json_response(sessions_collector.list_sessions(_runs_root()))


@api.get("/sessions/<session_id>")
def get_session(session_id):
    view = _session_view(session_id)
    if view is None:
        return error_response(f"session {session_id} not found")
    return json_response(SessionDetailResponse(meta=view.meta, agents=view.agents))


@api.get("/sessions/<session_id>/graph")
def get_session_graph(session_id):
    view = _session_view(session_id)
    if view is None:
        return error_response(f"session {session_id} not found")
    return json_response(view.graph)
