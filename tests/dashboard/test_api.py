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


def test_sessions_list(runs_root):
    r = _client(runs_root).get("/api/sessions")
    assert r.status_code == 200
    assert len(r.get_json()["sessions"]) == 1


def test_session_detail_meta_agents_no_graph(runs_root):
    c = _client(runs_root)
    sid = c.get("/api/sessions").get_json()["sessions"][0]["session_id"]
    body = c.get(f"/api/sessions/{sid}").get_json()
    assert "graph" not in body          # S3-A : détail = meta + agents, pas le graphe
    assert body["meta"]["session_id"] == sid
    assert len(body["agents"]) == len(DEMO_AGENTS)


def test_session_graph_edges_use_alias(runs_root):
    c = _client(runs_root)
    sid = c.get("/api/sessions").get_json()["sessions"][0]["session_id"]
    r = c.get(f"/api/sessions/{sid}/graph")
    assert r.status_code == 200
    g = r.get_json()
    assert g["steps"][0]["milestone_type"] == "input"  # modèle jalons
    assert all(("from" in e and "to" in e) for e in g["edges"])  # by_alias


def test_session_detail_404(runs_root):
    r = _client(runs_root).get("/api/sessions/nope")
    assert r.status_code == 404
    assert "error" in r.get_json()


def test_session_graph_404(runs_root):
    r = _client(runs_root).get("/api/sessions/nope/graph")
    assert r.status_code == 404
    assert "error" in r.get_json()


def test_health_checks_list(runs_root):
    r = _client(runs_root).get("/api/health-checks")
    assert r.status_code == 200
    assert len(r.get_json()["runs"]) == 1


def test_health_check_detail_has_agents(runs_root):
    c = _client(runs_root)
    rid = c.get("/api/health-checks").get_json()["runs"][0]["id"]
    body = c.get(f"/api/health-checks/{rid}").get_json()
    assert len(body["cases"]) == 2
    assert len(body["agents"]) == len(DEMO_AGENTS)


def test_health_check_graph_default_first_graphable(runs_root):
    c = _client(runs_root)
    rid = c.get("/api/health-checks").get_json()["runs"][0]["id"]
    r = c.get(f"/api/health-checks/{rid}/graph")  # sans task_id -> 1er cas graphable (S4-B)
    assert r.status_code == 200
    assert r.get_json()["steps"][0]["milestone_type"] == "input"  # modèle jalons


def test_health_check_graph_explicit_task(runs_root):
    c = _client(runs_root)
    rid = c.get("/api/health-checks").get_json()["runs"][0]["id"]
    detail = c.get(f"/api/health-checks/{rid}").get_json()
    graphable_tid = [cc["task_id"] for cc in detail["cases"] if cc["graphable"]][0]
    r = c.get(f"/api/health-checks/{rid}/graph?task_id={graphable_tid}")
    assert r.status_code == 200


def test_health_check_graph_quarantined_404(runs_root):
    c = _client(runs_root)
    rid = c.get("/api/health-checks").get_json()["runs"][0]["id"]
    detail = c.get(f"/api/health-checks/{rid}").get_json()
    quarantined_tid = [cc["task_id"] for cc in detail["cases"] if not cc["graphable"]][0]
    r = c.get(f"/api/health-checks/{rid}/graph?task_id={quarantined_tid}")
    assert r.status_code == 404


def test_health_check_detail_404(runs_root):
    r = _client(runs_root).get("/api/health-checks/nope")
    assert r.status_code == 404
    assert "error" in r.get_json()
