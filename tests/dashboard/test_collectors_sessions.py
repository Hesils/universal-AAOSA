from dashboard.collectors.sessions import list_sessions, session_detail


def test_list_sessions(runs_root):
    result = list_sessions(runs_root)
    assert len(result.sessions) == 1
    s = result.sessions[0]
    assert s.task_count == 2
    assert s.agent_count == 4


def test_list_sessions_empty(tmp_path):
    assert list_sessions(tmp_path).sessions == []


def test_session_detail_graph(runs_root):
    sid = list_sessions(runs_root).sessions[0].session_id
    view = session_detail(runs_root, sid)
    assert view is not None
    # Modèle jalons : le graphe rejoue le run primaire de la session (1 run/graphe).
    # Une session multi-tâches indépendantes ne rend que sa 1re tâche (limitation assumée).
    types = [st.milestone_type for st in view.graph.steps]
    assert types[0] == "input"
    assert "dispatch" in types
    assert types[-1] == "output"
    assert any(st.outcome == "qa_pass" for st in view.graph.steps)


def test_session_detail_not_found(runs_root):
    assert session_detail(runs_root, "nope") is None


def test_session_detail_has_agents(runs_root):
    from aaosa.demo.agents import DEMO_AGENTS
    sid = list_sessions(runs_root).sessions[0].session_id
    view = session_detail(runs_root, sid)
    assert view is not None
    assert len(view.agents) == len(DEMO_AGENTS)
    assert all(a.system_prompt for a in view.agents)
    assert {a.agent_id for a in view.agents} == {a.id for a in DEMO_AGENTS}
