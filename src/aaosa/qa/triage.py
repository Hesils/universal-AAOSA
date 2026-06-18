"""Agent de triage (B2) — auto-attribution de la cause d'un échec QA.

Remplace le triage manuel : un appel LLM classifie chaque TestCase unattributed
en "agent" / "task_spec" / "evaluator". Batch (hors chemin runtime). Ne mute
jamais l'input. Le reste de la boucle (routing via attribution dans test_set.py,
lifecycle.py, health_check.py) est inchangé.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from aaosa.qa.test_set import TestCase, TestSet
from aaosa.runtime.providers import LLMProvider


class TriageResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attribution: Literal["agent", "task_spec", "evaluator"]
    justification: str


def _build_triage_prompt(case: TestCase) -> str:
    required_tags = ", ".join(f"{t}:{elo}" for t, elo in case.task.required_tags.items())
    output = (
        case.wrong_output.content
        if case.wrong_output is not None
        else "[No output — the task was not claimed by any agent]"
    )
    criteria = "\n".join(
        f"- {c.name}{' (gate)' if c.gate else ''}"
        for c in case.evaluator_spec.criteria
    )
    return (
        "You are a quality triage specialist. An automated QA system flagged this "
        "agent output as a failure. Your task is to identify the root cause.\n\n"
        f"Task description:\n{case.task.description}\n\n"
        f"Required tags: {required_tags}\n\n"
        f"Agent output:\n{output}\n\n"
        f"QA evaluator criteria:\n{criteria}\n\n"
        f"Reference answer (if available):\n{case.reference or 'None'}\n\n"
        "Attribute the failure to exactly one of:\n"
        '- "agent": the output is genuinely poor for a well-formed task with fair '
        "evaluation criteria\n"
        '- "task_spec": the task description is ambiguous, malformed, or sets '
        "unrealistic expectations\n"
        '- "evaluator": the evaluation criteria are too strict, inconsistent, or '
        "inappropriate for this task"
    )


def triage_case(case: TestCase, provider: LLMProvider, model: str | None = None) -> TriageResult | None:
    """Classifie un seul TestCase. Retourne None si le LLM échoue (cas reste unattributed)."""
    prompt = _build_triage_prompt(case)
    return provider.parse(
        messages=[{"role": "user", "content": prompt}],
        schema=TriageResult,
        temperature=0,
        model=model,
    )


def triage_unattributed(test_set: TestSet, provider: LLMProvider, model: str | None = None) -> TestSet:
    """Retourne un nouveau TestSet avec les cas unattributed maintenant classifiés.

    Les cas déjà classifiés sont copiés tels quels (aucun appel LLM).
    Un cas dont le triage échoue reste unattributed. Ne mute pas l'input.
    """
    new_cases: list[TestCase] = []
    for case in test_set.cases:
        if case.attribution != "unattributed":
            new_cases.append(case)
            continue
        result = triage_case(case, provider, model=model)
        if result is None:
            new_cases.append(case)  # reste unattributed
        else:
            new_cases.append(case.model_copy(update={"attribution": result.attribution}))
    return TestSet(cases=new_cases)
