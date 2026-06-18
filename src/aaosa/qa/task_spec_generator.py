"""TaskSpecGenerator (B3) — corrige les descriptions de tâches malformées.

Consomme les cas attribués "task_spec" par B2 et réécrit `task.description` via
LLM. Après correction : attribution reset à "unattributed" (la tâche repasse par
B2), task.id / role / wrong_output conservés. Batch, ne mute jamais l'input.
Le reste de la boucle (active_cases, graduate, run_health_check) est inchangé.
"""

from pydantic import BaseModel, ConfigDict

from aaosa.qa.test_set import TestCase, TestSet
from aaosa.runtime.providers import LLMProvider


class TaskSpecFix(BaseModel):
    model_config = ConfigDict(extra="forbid")
    corrected_description: str
    justification: str


def _build_fix_prompt(case: TestCase) -> str:
    required_tags = "\n".join(f"- {t}: {elo}" for t, elo in case.task.required_tags.items())
    output = (
        case.wrong_output.content
        if case.wrong_output is not None
        else "[No output — task was not claimed]"
    )
    criteria = "\n".join(
        f"- {c.name}{' (gate)' if c.gate else ''}"
        for c in case.evaluator_spec.criteria
    )
    return (
        "You are a task specification specialist. An automated QA system determined "
        "that the following task description caused an agent failure because the task "
        "itself was malformed or ambiguous — not due to agent incompetence.\n\n"
        f"Original task description:\n{case.task.description}\n\n"
        f"Required agent capabilities (tags and minimum ELO levels):\n{required_tags}\n\n"
        f"Agent output that was flagged as failing:\n{output}\n\n"
        f"QA evaluator criteria:\n{criteria}\n\n"
        f"Reference answer (if available):\n{case.reference or 'None'}\n\n"
        "Rewrite the task description so that it is:\n"
        "- Clear and unambiguous — a qualified agent knows exactly what to produce\n"
        "- Achievable — given the required capabilities listed above\n"
        "- Specific — concrete expected output, not vague instructions\n"
        "- Fair — consistent with the evaluation criteria listed above\n\n"
        "Return only the corrected description in 'corrected_description'. Do not include "
        "explanations inside the description itself."
    )


def fix_task_spec(case: TestCase, provider: LLMProvider, model: str | None = None) -> TestCase | None:
    """Retourne un nouveau TestCase avec description corrigée et attribution='unattributed'.

    Retourne None si le LLM échoue (le cas reste task_spec dans le TestSet).
    Ne mute pas l'input.
    """
    prompt = _build_fix_prompt(case)
    result = provider.parse(
        messages=[{"role": "user", "content": prompt}],
        schema=TaskSpecFix,
        temperature=0,
        model=model,
    )
    if result is None:
        return None  # LLM failure — cas reste task_spec
    new_task = case.task.model_copy(update={"description": result.corrected_description})
    return case.model_copy(update={"task": new_task, "attribution": "unattributed"})


def fix_task_spec_cases(test_set: TestSet, provider: LLMProvider, model: str | None = None) -> TestSet:
    """Retourne un nouveau TestSet avec les cas task_spec corrigés. Autres cas inchangés.

    Les cas dont le fix échoue (LLM failure) restent task_spec. Ne mute pas l'input.
    """
    new_cases: list[TestCase] = []
    for case in test_set.cases:
        if case.attribution != "task_spec":
            new_cases.append(case)
            continue
        fixed = fix_task_spec(case, provider, model=model)
        new_cases.append(fixed if fixed is not None else case)
    return TestSet(cases=new_cases)
