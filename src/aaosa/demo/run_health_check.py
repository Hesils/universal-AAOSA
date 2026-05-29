from pathlib import Path

from dotenv import load_dotenv

from aaosa.demo.agents import DEMO_AGENTS
from aaosa.demo.tasks import (
    TASK_BUILD_DASHBOARD_UI,
    TASK_FIX_CSS_HOVER,
    TASK_OPTIMIZE_SQL,
    TASK_REFACTOR_REST_API,
    TASK_SECURITY_AUDIT,
    TASK_WRITE_PYTHON_TESTS,
)
from aaosa.qa.health_check import run_health_check, save_health_check
from aaosa.tracing.store import new_session_id
from aaosa.tracing.tracer import Tracer
from aaosa.qa.lifecycle import graduate
from aaosa.qa.spec import CriterionSpec, EvaluatorSpec
from aaosa.qa.test_set import TestCase, TestSet, active_cases
from aaosa.runtime.llm_client import create_client
from aaosa.runtime.runner import run_task


def _lenient_spec() -> EvaluatorSpec:
    return EvaluatorSpec(criteria=[
        CriterionSpec(name="non_empty", gate=True),
        CriterionSpec(name="min_length", params={"min_chars": 50}, weight=1.0),
    ])


def _strict_spec() -> EvaluatorSpec:
    # keyword impossible a obtenir d'un LLM -> FAIL garanti
    return EvaluatorSpec(criteria=[
        CriterionSpec(name="non_empty", gate=True),
        CriterionSpec(name="keyword_presence",
                      params={"keywords": ["BENCHMARK_APPROVED_v2b"]}, weight=1.0),
    ])


def build_demo_test_set() -> TestSet:
    return TestSet(cases=[
        # regression_guard/agent — CSS fix stable, surveille les régressions
        TestCase(
            task=TASK_FIX_CSS_HOVER,
            evaluator_spec=_lenient_spec(),
            origin="curated",
            role="regression_guard",
            attribution="agent",
        ),
        # fix_target/agent FAIL — SQL avec spec stricte, agent toujours en échec
        TestCase(
            task=TASK_OPTIMIZE_SQL,
            evaluator_spec=_strict_spec(),
            origin="runtime_failure",
            role="fix_target",
            attribution="agent",
        ),
        # fix_target/agent PASS → candidate à la graduation
        TestCase(
            task=TASK_WRITE_PYTHON_TESTS,
            evaluator_spec=_lenient_spec(),
            origin="runtime_failure",
            role="fix_target",
            attribution="agent",
        ),
        # fix_target/task_spec — spec ambiguë, quarantaine (cible TaskSpecGenerator V3)
        TestCase(
            task=TASK_REFACTOR_REST_API,
            evaluator_spec=_lenient_spec(),
            origin="runtime_failure",
            role="fix_target",
            attribution="task_spec",
        ),
        # fix_target/evaluator — évaluator trop strict, quarantaine
        TestCase(
            task=TASK_BUILD_DASHBOARD_UI,
            evaluator_spec=_strict_spec(),
            origin="runtime_failure",
            role="fix_target",
            attribution="evaluator",
        ),
        # fix_target/unattributed — pas encore diagnostiqué, quarantaine
        TestCase(
            task=TASK_SECURITY_AUDIT,
            evaluator_spec=_lenient_spec(),
            origin="runtime_failure",
            role="fix_target",
            attribution="unattributed",
        ),
    ])


def run_demo_health_check() -> None:
    load_dotenv()
    client = create_client()

    print("=== AAOSA Demo V2b - Health Check ===\n")

    test_set = build_demo_test_set()
    active = active_cases(test_set)
    quarantined = [c for c in test_set.cases if c not in active]

    print(f"Test set : {len(test_set.cases)} cas total")
    print(f"  Actifs   ({len(active)}) :")
    for c in active:
        print(f"    [{c.role}/{c.attribution}] {c.task.description[:60]}")
    print(f"  Quarantines ({len(quarantined)}) :")
    for c in quarantined:
        print(f"    [{c.role}/{c.attribution}] {c.task.description[:60]}")
    print()

    tracer = Tracer(session_id=new_session_id())
    print(f"Lancement health check (n_runs=3)...\n")
    report = run_health_check(DEMO_AGENTS, test_set, client, n_runs=3, tracer=tracer)

    print("=== Rapport ===")
    print(f"  Cas actifs            : {report.total_cases}")
    print(f"  fix_target pass rate  : {report.fix_target_pass_rate:.0%}")
    print(f"  regression_guard pass rate : {report.regression_guard_pass_rate:.0%}")
    print()

    print("  Resultats par cas :")
    for cr in report.case_results:
        flag = " [UNSTABLE]" if cr.unstable else ""
        case = next(c for c in test_set.cases if c.task.id == cr.task_id)
        print(f"    [{cr.role}/{case.attribution}] {case.task.description[:50]:<50}"
              f"  pass={cr.pass_rate:.0%} ({cr.pass_count}/{cr.n_runs}){flag}")
    print()

    print("  Quarantines :")
    for tid in report.task_spec_quarantined:
        case = next(c for c in test_set.cases if c.task.id == tid)
        print(f"    [task_spec]   {case.task.description[:60]}")
    for tid in report.evaluator_quarantined:
        case = next(c for c in test_set.cases if c.task.id == tid)
        print(f"    [evaluator]   {case.task.description[:60]}")
    for tid in report.unattributed:
        case = next(c for c in test_set.cases if c.task.id == tid)
        print(f"    [unattributed] {case.task.description[:60]}")
    print()

    print("=== Lifecycle : graduate() ===")
    updated = graduate(test_set, report, graduation_threshold=0.8)
    graduated = [
        c for c in updated.cases
        if next(o for o in test_set.cases if o.task.id == c.task.id).role == "fix_target"
        and c.role == "regression_guard"
    ]
    if graduated:
        for c in graduated:
            print(f"  PROMU -> regression_guard : {c.task.description[:60]}")
    else:
        print("  Aucune graduation (pass_rate < 0.8 sur tous les fix_target actifs)")

    target = save_health_check(report, test_set, tracer, Path("runs") / "health_checks")
    print(f"\nHealth check saved to {target}")


if __name__ == "__main__":
    run_demo_health_check()
