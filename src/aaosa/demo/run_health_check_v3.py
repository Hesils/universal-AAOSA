"""Démo V3 health check — boucle d'auto-amélioration B2 (triage) → B3 (task spec) → re-triage.

Lancer : .venv\\Scripts\\python src\\aaosa\\demo\\run_health_check_v3.py  (requiert OPENAI_API_KEY)
"""

from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from aaosa.demo.agents import DEMO_AGENTS
from aaosa.demo.tasks import TASK_OPTIMIZE_SQL, TASK_REFACTOR_REST_API, TASK_SECURITY_AUDIT
from aaosa.qa.adaptive import build_adaptive_spec, build_llm_spec
from aaosa.qa.health_check import run_health_check, save_health_check
from aaosa.qa.task_spec_generator import fix_task_spec_cases
from aaosa.qa.test_set import TestCase, TestSet, active_cases
from aaosa.qa.triage import triage_unattributed
from aaosa.runtime.llm_client import create_client
from aaosa.schemas.output import LLMMetadata, Output
from aaosa.schemas.task import Task
from aaosa.tracing.store import new_session_id
from aaosa.tracing.tracer import Tracer


def _wrong_output(task: Task, content: str) -> Output:
    return Output(
        task_id=task.id, agent_id="seed-agent", content=content,
        llm_metadata=LLMMetadata(model_name="seed", tokens_in=1, tokens_out=1, latency_ms=1.0),
    )


def _spec_for(task: Task, client: OpenAI | None):
    """Spec LLM (B1) si un client est fourni — exerce llm_check via le SpecEvaluator
    corrigé que run_health_check construit avec le client. Sinon spec déterministe
    (build offline reproductible pour le test unitaire)."""
    return build_llm_spec(task, client) if client is not None else build_adaptive_spec(task)


def build_seed_test_set(client: OpenAI | None = None) -> TestSet:
    """Cas runtime_failure non attribués, avec wrong_output canned (matière au triage)."""
    return TestSet(cases=[
        # output vraiment faible -> triage attendu "agent"
        TestCase(
            task=TASK_SECURITY_AUDIT,
            evaluator_spec=_spec_for(TASK_SECURITY_AUDIT, client),
            origin="runtime_failure", role="fix_target", attribution="unattributed",
            wrong_output=_wrong_output(TASK_SECURITY_AUDIT, "Looks fine to me."),
        ),
        # tâche ambiguë -> triage attendu "task_spec" -> corrigée par B3
        TestCase(
            task=TASK_REFACTOR_REST_API,
            evaluator_spec=_spec_for(TASK_REFACTOR_REST_API, client),
            origin="runtime_failure", role="fix_target", attribution="unattributed",
            wrong_output=_wrong_output(TASK_REFACTOR_REST_API, "I refactored some things."),
        ),
        TestCase(
            task=TASK_OPTIMIZE_SQL,
            evaluator_spec=_spec_for(TASK_OPTIMIZE_SQL, client),
            origin="runtime_failure", role="fix_target", attribution="unattributed",
            wrong_output=_wrong_output(TASK_OPTIMIZE_SQL, "Added an index."),
        ),
    ])


def _print_attributions(label: str, ts: TestSet) -> None:
    print(f"-- {label} --")
    for c in ts.cases:
        print(f"   [{c.attribution:<12}] {c.task.description[:55]}")
    print()


def run_demo_health_check_v3() -> None:
    load_dotenv()
    client = create_client()
    print("=== AAOSA Demo V3 — Health check + boucle B2/B3 ===\n")

    seed = build_seed_test_set(client)
    _print_attributions("Seed (toutes unattributed)", seed)

    triaged = triage_unattributed(seed, client)       # B2
    _print_attributions("Apres triage (B2)", triaged)

    fixed = fix_task_spec_cases(triaged, client)       # B3 (reset task_spec -> unattributed)
    _print_attributions("Apres correction task_spec (B3)", fixed)

    retriaged = triage_unattributed(fixed, client)     # re-triage
    _print_attributions("Apres re-triage (B2)", retriaged)

    active = active_cases(retriaged)
    print(f"Cas actifs : {len(active)}\n")

    tracer = Tracer(session_id=new_session_id())
    report = run_health_check(DEMO_AGENTS, retriaged, client, n_runs=3, tracer=tracer)

    print("=== Rapport ===")
    print(f"  fix_target pass rate       : {report.fix_target_pass_rate:.0%}")
    print(f"  regression_guard pass rate : {report.regression_guard_pass_rate:.0%}")
    for cr in report.case_results:
        flag = " [UNSTABLE]" if cr.unstable else ""
        print(f"    {cr.role:<16} pass={cr.pass_rate:.0%} ({cr.pass_count}/{cr.n_runs}){flag}")

    target = save_health_check(report, retriaged, tracer, Path("runs") / "health_checks", agents=DEMO_AGENTS)
    print(f"\nHealth check saved to {target}")


if __name__ == "__main__":
    run_demo_health_check_v3()
