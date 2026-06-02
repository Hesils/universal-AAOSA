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
