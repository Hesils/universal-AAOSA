from dashboard.collectors.health_checks import list_runs, run_detail


def test_list_runs(runs_root):
    result = list_runs(runs_root)
    assert len(result.runs) == 1
    r = result.runs[0]
    assert r.total_cases == 1
    assert r.quarantined_count == 1
    assert abs(r.regression_guard_pass_rate - 2 / 3) < 1e-9


def test_list_runs_empty(tmp_path):
    assert list_runs(tmp_path).runs == []


def test_run_detail_join(runs_root):
    rid = list_runs(runs_root).runs[0].id
    view = run_detail(runs_root, rid)
    assert view is not None
    assert len(view.cases) == 2

    active = [c for c in view.cases if c.graphable]
    quarantined = [c for c in view.cases if not c.graphable]

    assert len(active) == 1
    assert active[0].role == "regression_guard"
    assert active[0].result is not None
    assert active[0].result.pass_count == 2

    assert len(quarantined) == 1
    assert quarantined[0].attribution == "task_spec"
    assert quarantined[0].result is None
    assert quarantined[0].evaluator_spec.criteria[0].name == "non_empty"


def test_run_detail_not_found(runs_root):
    assert run_detail(runs_root, "nope") is None
