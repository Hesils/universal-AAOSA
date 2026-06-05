import logging
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field

from aaosa.qa.criteria import CRITERIA_REGISTRY
from aaosa.qa.spec import CriterionSpec, EvaluatorSpec, JudgeSpec
from aaosa.schemas.elo import ELO_COMPETENT_MIN, ELO_EXPERT_MIN
from aaosa.schemas.task import Task

logger = logging.getLogger(__name__)


# --- Schémas LLM-facing (structured output) -------------------------------
# OpenAI structured output interdit les dict ouverts (cf. divider.SubTaskSpec).
# CriterionSpec.params est un dict → on ne peut PAS le passer en response_format.
# On expose donc des paramètres explicites et on reconstruit le dict côté Python.
class _LLMCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    weight: float = 1.0
    # Pas de champ `gate` : seul "non_empty" peut être un gate (invariant V2b),
    # injecté par _ensure_non_empty_gate. Le LLM ne propose que des critères scorés.
    # params possibles, aplatis (un critère n'en utilise qu'un sous-ensemble) :
    min_chars: int | None = None          # min_length
    description: str | None = None        # llm_check
    keywords: list[str] | None = None     # keyword_presence
    kind: str | None = None               # format_check

    def to_criterion(self) -> CriterionSpec:
        params: dict = {}
        if self.min_chars is not None:
            params["min_chars"] = self.min_chars
        if self.description is not None:
            params["description"] = self.description
        if self.keywords is not None:
            params["keywords"] = self.keywords
        if self.kind is not None:
            params["kind"] = self.kind
        return CriterionSpec(name=self.name, params=params, weight=self.weight)


class _LLMJudge(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["rubric", "reference_based"] = "rubric"
    rubric: list[str]
    # Pas de champ `weight` : le judge n'est jamais le signal primaire (invariant
    # V2b). Poids verrouillé à 0.3 via le défaut JudgeSpec — le LLM ne le contrôle pas.

    def to_judge(self) -> JudgeSpec:
        return JudgeSpec(mode=self.mode, rubric=self.rubric)


class _LLMEvaluatorSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    criteria: list[_LLMCriterion]
    judge: _LLMJudge | None = None
    success_threshold: float = 0.7

    def to_spec(self) -> EvaluatorSpec:
        return EvaluatorSpec(
            criteria=[c.to_criterion() for c in self.criteria],
            judge=self.judge.to_judge() if self.judge is not None else None,
            success_threshold=self.success_threshold,
        )


def _derive_threshold(task: Task) -> float:
    """success_threshold dérivé du max des ELO requis (déterministe, zéro LLM)."""
    elos = task.required_tags.values()
    if not elos:
        return 0.7
    max_elo = max(elos)
    if max_elo >= ELO_EXPERT_MIN:        # 85
        return 0.8
    if max_elo >= ELO_COMPETENT_MIN:     # 30
        return 0.7
    return 0.6


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

    return EvaluatorSpec(criteria=criteria, judge=judge, success_threshold=_derive_threshold(task))


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
    context_section = f"# Contexte domaine\n{task.context}\n\n" if task.context else ""
    return (
        "Tu génères une EvaluatorSpec pour évaluer la réponse d'un agent à cette tâche.\n\n"
        f"# Tâche\n{task.description}\n\n"
        f"{context_section}"
        f"# Tags requis\n{', '.join(task.required_tags)}\n\n"
        f"# Critères prédéfinis disponibles (suggestions)\n{predefined}\n\n"
        "# Critère adaptatif libre\n"
        '"llm_check" accepte un param "description" (str) — utilise-le pour tout critère '
        "sémantique spécifique à cette tâche qui ne correspond à aucun critère prédéfini.\n"
        'Exemple : {"name": "llm_check", "params": {"description": "La réponse doit inclure '
        'des exemples de code avec explications"}, "weight": 1.5}\n\n'
        "# Règles\n"
        '- "non_empty" est ajouté automatiquement comme unique gate — ne le déclare pas\n'
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
            response_format=_LLMEvaluatorSpec,
        )
        parsed = response.choices[0].message.parsed
        if parsed is None:
            raise ValueError("LLM returned no parsed _LLMEvaluatorSpec")
        spec = _filter_unknown_criteria(parsed.to_spec(), task)
        return _ensure_non_empty_gate(spec)
    except Exception as e:
        # Fallback runtime-safe (un hoquet LLM ne casse pas le run) mais PLUS silencieux :
        # c'est ce except nu + le dict ouvert de CriterionSpec qui masquaient le bug spec.
        logger.warning("build_llm_spec fallback to deterministic spec: %s", e)
        return build_adaptive_spec(task)
