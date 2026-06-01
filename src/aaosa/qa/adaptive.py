from openai import OpenAI

from aaosa.qa.criteria import CRITERIA_REGISTRY
from aaosa.qa.spec import CriterionSpec, EvaluatorSpec, JudgeSpec
from aaosa.schemas.elo import ELO_EXPERT_MIN
from aaosa.schemas.task import Task


def build_adaptive_spec(task: Task) -> EvaluatorSpec:
    n_tags = len(task.required_tags)

    criteria = [
        CriterionSpec(name="non_empty", gate=True),
        CriterionSpec(name="min_length", params={"min_chars": 50 * n_tags}, weight=1.0),
    ]

    judge = None
    if any(elo >= ELO_EXPERT_MIN for elo in task.required_tags.values()):
        judge = JudgeSpec(
            mode="rubric",
            rubric=["correctness", "completeness", "relevance"],
        )

    return EvaluatorSpec(criteria=criteria, judge=judge)


def _filter_unknown_criteria(spec: EvaluatorSpec, task: Task) -> EvaluatorSpec:
    """Retire les CriterionSpec dont le name est inconnu de CRITERIA_REGISTRY.

    Défense secondaire contre les noms inventés par le LLM. Si plus aucun
    critère ne subsiste, retombe sur le spec déterministe.
    """
    kept = [c for c in spec.criteria if c.name in CRITERIA_REGISTRY]
    if not kept:
        return build_adaptive_spec(task)
    return spec.model_copy(update={"criteria": kept})


def _ensure_non_empty_gate(spec: EvaluatorSpec) -> EvaluatorSpec:
    """Invariant : un critère non_empty avec gate=True est toujours présent."""
    criteria = list(spec.criteria)
    for i, c in enumerate(criteria):
        if c.name == "non_empty":
            if not c.gate:
                criteria[i] = c.model_copy(update={"gate": True})
            return spec.model_copy(update={"criteria": criteria})
    criteria.insert(0, CriterionSpec(name="non_empty", gate=True))
    return spec.model_copy(update={"criteria": criteria})


def _build_prompt(task: Task) -> str:
    predefined = ", ".join(sorted(CRITERIA_REGISTRY))
    return (
        "Tu génères une EvaluatorSpec pour évaluer la réponse d'un agent à cette tâche.\n\n"
        f"# Tâche\n{task.description}\n\n"
        f"# Tags requis\n{', '.join(task.required_tags)}\n\n"
        f"# Critères prédéfinis disponibles (suggestions)\n{predefined}\n\n"
        "# Critère adaptatif libre\n"
        '"llm_check" accepte un param "description" (str) — utilise-le pour tout critère '
        "sémantique spécifique à cette tâche qui ne correspond à aucun critère prédéfini.\n"
        'Exemple : {"name": "llm_check", "params": {"description": "La réponse doit inclure '
        'des exemples de code avec explications"}, "weight": 1.5}\n\n'
        "# Règles\n"
        '- Toujours inclure "non_empty" comme gate=True\n'
        '- Ajouter "min_length" si la tâche attend une réponse détaillée\n'
        '- Utiliser "llm_check" pour des critères qualitatifs propres à cette tâche\n'
        '- Ajouter un judge (mode "rubric") si la tâche est complexe ou ambiguë\n'
        '- Tout nom hors de la liste prédéfinie ET hors "llm_check" sera ignoré\n'
        "- success_threshold entre 0.5 et 0.9 selon la criticité"
    )


def build_llm_spec(task: Task, client: OpenAI) -> EvaluatorSpec:
    """Génère un EvaluatorSpec via LLM (structured output).

    Fallback automatique sur build_adaptive_spec si le LLM échoue.
    Post-filtre les critères inconnus de CRITERIA_REGISTRY et garantit
    l'invariant non_empty gate=True.
    """
    try:
        response = client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            temperature=0.0,
            messages=[
                {"role": "system", "content": "Tu produis une spec d'évaluation déclarative."},
                {"role": "user", "content": _build_prompt(task)},
            ],
            response_format=EvaluatorSpec,
        )
        parsed = response.choices[0].message.parsed
        if parsed is None:
            raise ValueError("LLM returned no parsed EvaluatorSpec")
        spec = _filter_unknown_criteria(parsed, task)
        return _ensure_non_empty_gate(spec)
    except Exception:
        return build_adaptive_spec(task)
