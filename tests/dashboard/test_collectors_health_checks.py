from dashboard.collectors.health_checks import list_runs


def test_list_runs(runs_root):
    result = list_runs(runs_root)
    assert len(result.runs) == 1
    r = result.runs[0]
    assert r.total_cases == 1
    assert r.quarantined_count == 1
    assert abs(r.regression_guard_pass_rate - 2 / 3) < 1e-9


def test_list_runs_empty(tmp_path):
    assert list_runs(tmp_path).runs == []
