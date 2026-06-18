"""Diagnostic d'échec inline (D3) — chemin parallèle au triage batch B2/B3.

`diagnose_failure` classe un qa_fail live en agent / evaluator / task_spec /
unattributed et propose des consignes courtes pour un retry. Pur : prend des
données, retourne un DiagnosticResult (ou None sur échec LLM). Aucun accès au
runtime, au store, ni à l'historique. Indépendant de qa/triage.py (B2).
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from aaosa.qa.protocol import QAResult
from aaosa.runtime.providers import LLMProvider
from aaosa.schemas.output import Output
from aaosa.schemas.task import Task


class FailureContext(BaseModel):
    """Contexte d'un échec, passé au divider sur la route task_spec (D3)."""
    model_config = ConfigDict(extra="forbid")
    failed_output: Output
    qa_result: QAResult
    diagnostic_reason: str


class DiagnosticResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attribution: Literal["agent", "evaluator", "task_spec", "unattributed"]
    consignes: str | None = None   # présent si l'agent peut réessayer avec des clarifications
    reason: str                    # alimente FailureContext.diagnostic_reason


def _build_diagnostic_prompt(task: Task, output: Output, qa_result: QAResult) -> str:
    """Construit le prompt pour `diagnose_failure`."""
    failed = [name for name, ok in qa_result.criteria_results.items() if not ok]
    context_section = f"Contexte domaine:\n{task.context}\n\n" if task.context else ""
    return (
        "Une réponse d'agent vient d'échouer au QA sur un run live. Décide quoi faire "
        "MAINTENANT pour récupérer.\n\n"
        f"Description de la tâche:\n{task.description}\n\n"
        f"{context_section}"
        f"Réponse produite par l'agent:\n{output.content}\n\n"
        f"Verdict QA (score={qa_result.score:.2f}): {qa_result.reason}\n"
        f"Critères ratés: {', '.join(failed) or 'aucun critère scoré nommé'}\n\n"
        "Attribue la cause à exactement une valeur :\n"
        '- "agent": la réponse est objectivement faible, l\'agent peut réessayer avec '
        "des clarifications\n"
        '- "evaluator": les critères d\'évaluation sont inadaptés (trop stricts, mauvais '
        "critères) — la réponse est probablement correcte\n"
        '- "task_spec": la description de la tâche est ambiguë et doit être décomposée/clarifiée\n'
        '- "unattributed": cause indéterminée\n\n'
        'Si "agent" ou "evaluator", fournis des "consignes" courtes et actionnables que '
        "l'agent suivra à sa prochaine tentative. Sinon laisse consignes vide.\n"
        'Donne aussi un "reason" bref expliquant ton attribution.'
    )


def diagnose_failure(
    task: Task,
    output: Output,
    qa_result: QAResult,
    provider: LLMProvider,
    model: str | None = None,
) -> DiagnosticResult | None:
    """Diagnostique un qa_fail. Retourne None si le LLM échoue (caller → unattributed)."""
    prompt = _build_diagnostic_prompt(task, output, qa_result)
    return provider.parse(
        messages=[{"role": "user", "content": prompt}],
        schema=DiagnosticResult,
        temperature=0,
        model=model,
    )
