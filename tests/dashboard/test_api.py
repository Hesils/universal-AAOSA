from aaosa.demo.agents import DEMO_AGENTS
from dashboard.app import create_app
from dashboard.config import DashboardConfig


def _client(runs_root):
    return create_app(DashboardConfig(runs_root=runs_root)).test_client()


def test_infra_endpoint(runs_root):
    r = _client(runs_root).get("/api/infra")
    assert r.status_code == 200
    assert r.headers["Cache-Control"] == "no-store"
    assert r.get_json()["session_count"] == 1


def test_agents_list(runs_root):
    r = _client(runs_root).get("/api/agents")
    assert r.status_code == 200
    assert r.headers["Cache-Control"] == "no-store"
    assert len(r.get_json()["agents"]) == len(DEMO_AGENTS)


def test_agent_detail(runs_root):
    r = _client(runs_root).get(f"/api/agents/{DEMO_AGENTS[0].id}")
    assert r.status_code == 200
    assert r.headers["Cache-Control"] == "no-store"
    assert r.get_json()["system_prompt"]


def test_agent_detail_404(runs_root):
    r = _client(runs_root).get("/api/agents/nope")
    assert r.status_code == 404
    assert "error" in r.get_json()
    assert r.headers["Cache-Control"] == "no-store"
