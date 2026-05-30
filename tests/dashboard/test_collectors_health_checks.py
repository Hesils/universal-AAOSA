from aaosa.demo.agents import DEMO_AGENTS
from dashboard.collectors.health_checks import case_graph, list_runs, run_detail


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


def test_case_graph_active(runs_root):
    rid = list_runs(runs_root).runs[0].id
    active = [c for c in run_detail(runs_root, rid).cases if c.graphable][0]
    graph = case_graph(runs_root, rid, active.task_id)
    assert graph is not None
    assert len(graph.steps) == 1
    step = graph.steps[0]
    assert step.outcome == "qa_pass"
    # _synth_meta remplit l'overlay Input depuis le TestSet (sinon vide)
    assert step.detail.input.description == active.description
    assert step.detail.input.required_tags == active.required_tags


def test_case_graph_quarantined_returns_none(runs_root):
    rid = list_runs(runs_root).runs[0].id
    quarantined = [c for c in run_detail(runs_root, rid).cases if not c.graphable][0]
    assert case_graph(runs_root, rid, quarantined.task_id) is None


def test_run_detail_has_agents(runs_root):
    rid = list_runs(runs_root).runs[0].id
    view = run_detail(runs_root, rid)
    assert view is not None
    assert len(view.agents) == len(DEMO_AGENTS)
    assert all(a.system_prompt for a in view.agents)
