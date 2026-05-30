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
    assert len(view.graph.steps) == 2
    outcomes = {st.outcome for st in view.graph.steps}
    assert "qa_pass" in outcomes
    assert "unassigned" in outcomes


def test_session_detail_not_found(runs_root):
    assert session_detail(runs_root, "nope") is None
