"""Démo V3 health check — boucle d'auto-amélioration B2 (triage) → B3 (task spec) → re-triage.

Lancer : .venv\\Scripts\\python src\\aaosa\\demo\\run_health_check_v3.py  (requiert OPENAI_API_KEY)
"""

from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from aaosa.demo.agents import DEMO_AGENTS
from aaosa.runtime.providers import LLMProvider
from aaosa.demo.tasks import TASK_SECURITY_AUDIT
from aaosa.qa.adaptive import build_adaptive_spec, build_llm_spec
from aaosa.qa.health_check import run_health_check, save_health_check
from aaosa.qa.spec import CriterionSpec, EvaluatorSpec
from aaosa.qa.task_spec_generator import fix_task_spec_cases
from aaosa.qa.test_set import TestCase, TestSet, active_cases
from aaosa.qa.triage import triage_unattributed
from aaosa.runtime.llm_client import create_provider
from aaosa.schemas.output import LLMMetadata, Output
from aaosa.schemas.task import Task
from aaosa.tracing.store import new_session_id
from aaosa.tracing.tracer import Tracer


# Tâches volontairement dégénérées — matériel de seed uniquement, jamais dans DEMO_TASKS.
# Contraintes mutuellement exclusives -> infaisable tel quel : le triage doit imputer
# la tâche (task_spec), pas l'agent. Combiné avec un output de bonne foi (cf. seed).
TASK_CONTRADICTORY = Task(
    description=(
        "Rewrite the entire authentication module in a single line of code while adding "
        "full OAuth2, multi-factor authentication, and audit logging — without changing "
        "any existing function signatures"
    ),
    required_tags={"backend": 70, "python": 70},
)

TASK_STATUS_CODE = Task(
    description="State the correct HTTP status code for a successful DELETE with no body",
    required_tags={"backend": 30},
)

# Spec inadaptée pour le cas evaluator : gate min_length absurde sur une réponse concise.
# Construite sans LLM -> le chemin offline du seed reste constructible.
_MISMATCHED_SPEC = EvaluatorSpec(criteria=[
    CriterionSpec(name="non_empty", gate=True),
    CriterionSpec(name="min_length", params={"min_chars": 2000}, gate=True),
])


def _wrong_output(task: Task, content: str) -> Output:
    return Output(
        task_id=task.id, agent_id="seed-agent", content=content,
        llm_metadata=LLMMetadata(model_name="seed", tokens_in=1, tokens_out=1, latency_ms=1.0),
    )


def _spec_for(task: Task, provider: LLMProvider | None):
    """Spec LLM (B1) si un provider est fourni — exerce llm_check via le SpecEvaluator
    corrigé que run_health_check construit avec le provider. Sinon spec déterministe
    (build offline reproductible pour le test unitaire)."""
    return build_llm_spec(task, provider) if provider is not None else build_adaptive_spec(task)


def build_seed_test_set(provider: LLMProvider | None = None) -> TestSet:
    """Trois cas runtime_failure non attribués, conçus pour orienter le triage (B2)
    vers trois attributions distinctes. Voir le design 2026-06-03.

    - agent     : tâche bien formée + output nul
    - task_spec : tâche aux contraintes contradictoires + output de bonne foi qui
                  pointe l'infaisabilité (corrigée par B3 ensuite)
    - evaluator : bon output + tâche claire mais gate min_length inadapté
    """
    return TestSet(cases=[
        # tâche bien formée + output nul -> triage attendu "agent"
        TestCase(
            task=TASK_SECURITY_AUDIT,
            evaluator_spec=_spec_for(TASK_SECURITY_AUDIT, provider),
            origin="runtime_failure", role="fix_target", attribution="unattributed",
            wrong_output=_wrong_output(TASK_SECURITY_AUDIT, "Looks fine to me."),
        ),
        # contraintes contradictoires + effort de bonne foi -> triage attendu "task_spec" -> B3
        TestCase(
            task=TASK_CONTRADICTORY,
            evaluator_spec=_spec_for(TASK_CONTRADICTORY, provider),
            origin="runtime_failure", role="fix_target", attribution="unattributed",
            wrong_output=_wrong_output(
                TASK_CONTRADICTORY,
                "These constraints are mutually exclusive: OAuth2, MFA, and audit logging "
                "cannot coexist in a single line of code, and adding MFA necessarily changes "
                "the authenticate() signature, which the task forbids. I cannot satisfy all "
                "of them at once. Please relax either the single-line constraint or the "
                "no-signature-change constraint so I can implement a correct solution.",
            ),
        ),
        # bon output + tâche claire mais gate min_length inadapté -> triage attendu "evaluator"
        TestCase(
            task=TASK_STATUS_CODE,
            evaluator_spec=_MISMATCHED_SPEC,
            origin="runtime_failure", role="fix_target", attribution="unattributed",
            wrong_output=_wrong_output(TASK_STATUS_CODE, "204 No Content."),
        ),
    ])


def _print_attributions(label: str, ts: TestSet) -> None:
    print(f"-- {label} --")
    for c in ts.cases:
        print(f"   [{c.attribution:<12}] {c.task.description[:55]}")
    print()


def run_demo_health_check_v3() -> None:
    load_dotenv()
    provider = create_provider()
    print("=== AAOSA Demo V3 — Health check + boucle B2/B3 ===\n")

    seed = build_seed_test_set(provider)
    _print_attributions("Seed (toutes unattributed)", seed)

    triaged = triage_unattributed(seed, provider)       # B2
    _print_attributions("Apres triage (B2)", triaged)

    fixed = fix_task_spec_cases(triaged, provider)       # B3 (reset task_spec -> unattributed)
    _print_attributions("Apres correction task_spec (B3)", fixed)

    retriaged = triage_unattributed(fixed, provider)     # re-triage
    _print_attributions("Apres re-triage (B2)", retriaged)

    active = active_cases(retriaged)
    print(f"Cas actifs : {len(active)}\n")

    tracer = Tracer(session_id=new_session_id())
    report = run_health_check(DEMO_AGENTS, retriaged, provider, n_runs=3, tracer=tracer)

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
