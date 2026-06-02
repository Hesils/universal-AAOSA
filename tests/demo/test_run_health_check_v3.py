from aaosa.demo.run_health_check_v3 import build_seed_test_set, run_demo_health_check_v3
from aaosa.qa.test_set import TestSet


def test_build_seed_test_set_all_unattributed_with_wrong_output():
    ts = build_seed_test_set()
    assert isinstance(ts, TestSet)
    assert len(ts.cases) >= 1
    assert all(c.attribution == "unattributed" for c in ts.cases)
    assert all(c.origin == "runtime_failure" for c in ts.cases)
    assert all(c.wrong_output is not None for c in ts.cases)


def test_run_demo_health_check_v3_is_callable():
    assert callable(run_demo_health_check_v3)


def test_seed_designed_for_full_triage_taxonomy():
    ts = build_seed_test_set()  # chemin offline (client=None)
    assert len(ts.cases) == 3

    descriptions = [c.task.description for c in ts.cases]
    # tâche réellement vague -> visera "task_spec" au triage
    assert "Improve the codebase and make it better" in descriptions
    # tâche factuelle concise -> visera "evaluator" au triage
    status_case = next(
        c for c in ts.cases if "status code" in c.task.description.lower()
    )

    # le cas evaluator porte un gate min_length inadapté + un bon output
    gate_names = {cr.name for cr in status_case.evaluator_spec.criteria if cr.gate}
    assert "min_length" in gate_names
    assert status_case.wrong_output.content == "204 No Content."
