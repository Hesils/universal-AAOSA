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


# ---------- live-mode cache gating ----------

from datetime import datetime, timezone
from pathlib import Path

from aaosa.tracing.events import Phase1FilteredEvent, UnassignedEvent
from aaosa.tracing.store import SessionMeta, SessionTaskRecord


def _write_session_partial(root: Path, sid: str, status: str, task_id: str) -> Path:
    """Écrit une session avec une trace *incomplète* : seulement un Phase1FilteredEvent
    (dispatch non encore résolu). L'UnassignedEvent sera appendé plus tard pour simuler
    la croissance live."""
    sdir = root / "sessions" / sid
    sdir.mkdir(parents=True, exist_ok=True)
    now = datetime(2026, 6, 8, 11, 0, 0, tzinfo=timezone.utc)
    initial_event = Phase1FilteredEvent(
        session_id=sid, task_id=task_id, agent_id="a1", passed=False, fit_score=0.1
    )
    (sdir / "trace.jsonl").write_text(initial_event.model_dump_json() + "\n", encoding="utf-8")
    meta = SessionMeta(
        session_id=sid, started_at=now, ended_at=now, status=status,
        tasks=[SessionTaskRecord(id=task_id, description="root task",
                                 winner_agent_id=None, outcome="unassigned",
                                 required_tags={})],
        agent_ids=["a1"],
    )
    (sdir / "meta.json").write_text(meta.model_dump_json(indent=2), encoding="utf-8")
    return sdir


def test_sessions_list_includes_status(runs_root):
    r = _client(runs_root).get("/api/sessions")
    assert r.status_code == 200
    assert all("status" in s for s in r.get_json()["sessions"])


def test_running_session_graph_not_cached_reflects_growth(runs_root):
    # Trace initiale : Phase1FilteredEvent seul (dispatch sans résolution).
    # Après le 1er GET, on appende l'UnassignedEvent → unassigned_reason passe de None à "y".
    # La session est "running" → pas de cache → g2 doit refléter la nouvelle ligne.
    sdir = _write_session_partial(runs_root, "2026-06-08T11-00-00-live", "running", "root")
    c = _client(runs_root)
    g1 = c.get("/api/sessions/2026-06-08T11-00-00-live/graph").get_json()
    dispatch1 = g1["steps"][1]  # dispatch est le 2e step (INPUT puis DISPATCH)
    assert dispatch1["milestone_type"] == "dispatch", (
        "steps[1] n'est plus le jalon dispatch — build_graph a changé d'ordre"
    )
    assert dispatch1["detail"]["dispatch"]["unassigned_reason"] is None
    with (sdir / "trace.jsonl").open("a", encoding="utf-8") as f:
        f.write(UnassignedEvent(session_id="2026-06-08T11-00-00-live", task_id="root", reason="y").model_dump_json() + "\n")
    g2 = c.get("/api/sessions/2026-06-08T11-00-00-live/graph").get_json()
    dispatch2 = g2["steps"][1]
    assert dispatch2["milestone_type"] == "dispatch", (
        "steps[1] n'est plus le jalon dispatch — build_graph a changé d'ordre"
    )
    assert dispatch2["detail"]["dispatch"]["unassigned_reason"] == "y"
    assert g2 != g1


def test_complete_session_graph_is_cached(runs_root):
    sdir = _write_session_partial(runs_root, "2026-06-08T11-30-00-done", "complete", "root")
    c = _client(runs_root)
    g1 = c.get("/api/sessions/2026-06-08T11-30-00-done/graph").get_json()
    with (sdir / "trace.jsonl").open("a", encoding="utf-8") as f:
        f.write(UnassignedEvent(session_id="2026-06-08T11-30-00-done", task_id="root", reason="y").model_dump_json() + "\n")
    g2 = c.get("/api/sessions/2026-06-08T11-30-00-done/graph").get_json()
    assert g2 == g1
