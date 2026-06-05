import logging
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field

from aaosa.qa.criteria import CRITERIA_REGISTRY
from aaosa.qa.diagnostic import FailureContext
from aaosa.qa.spec import CriterionSpec, EvaluatorSpec, JudgeSpec
from aaosa.schemas.elo import ELO_COMPETENT_MIN, ELO_EXPERT_MIN
from aaosa.schemas.task import Task

logger = logging.getLogger(__name__)


# --- Schémas LLM-facing (structured output) -------------------------------
# OpenAI structured output interdit les dict ouverts. On expose des params
# explicites par type et on reconstruit le dict CriterionSpec.params côté Python.
# `type` est le discriminant : to_criterion() ne copie que les params du type
# (encode le lien name ↔ params — un min_length ne peut pas porter de keywords).
_CriterionType = Literal[
    "min_length", "keyword_presence", "llm_check", "format_check", "references_tags"
]
_Importance = Literal["critique", "normal", "mineur"]
_IMPORTANCE_WEIGHT: dict[str, float] = {"critique": 3.0, "normal": 2.0, "mineur": 1.0}


class _LLMCriterion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: _CriterionType
    importance: _Importance = "normal"
    rationale: str = ""
    # Pas de `weight` (l'importance discrète le dérive) ni de `gate`
    # (seul non_empty est gate, injecté par _ensure_non_empty_gate).
    # params par type, aplatis ; gardés par type dans to_criterion :
    min_chars: int | None = None          # min_length
    keywords: list[str] | None = None     # keyword_presence
    description: str | None = None        # llm_check
    kind: str | None = None               # format_check

    def to_criterion(self) -> CriterionSpec:
        params: dict = {}
        if self.type == "min_length" and self.min_chars is not None:
            params["min_chars"] = self.min_chars
        elif self.type == "keyword_presence" and self.keywords is not None:
            params["keywords"] = self.keywords
        elif self.type == "llm_check" and self.description is not None:
            params["description"] = self.description
        elif self.type == "format_check" and self.kind is not None:
            params["kind"] = self.kind
        # references_tags : aucun param
        return CriterionSpec(
            name=self.type,
            params=params,
            weight=_IMPORTANCE_WEIGHT[self.importance],
            rationale=self.rationale,
        )


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
    # Pas de success_threshold : dérivé déterministiquement de task.required_tags.

    def to_spec(self) -> EvaluatorSpec:
        return EvaluatorSpec(
            criteria=[c.to_criterion() for c in self.criteria],
            judge=self.judge.to_judge() if self.judge is not None else None,
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


_MAX_LLM_CHECK = 4
_MAX_SCORED = 6


def _apply_caps(criteria: list[CriterionSpec]) -> list[CriterionSpec]:
    """Troncature déterministe : ≤ 4 llm_check, ≤ 6 critères scorés au total.

    Tri par importance (weight) décroissant, tri stable → ordre d'émission
    préservé à importance égale. Les gates ne sont pas concernés (placés en tête,
    non comptés). On coupe d'abord l'excès de llm_check, puis le total à 6.
    """
    gates = [c for c in criteria if c.gate]
    scored = [c for c in criteria if not c.gate]
    ordered = sorted(scored, key=lambda c: -c.weight)  # stable
    kept: list[CriterionSpec] = []
    llm_seen = 0
    for c in ordered:
        if c.name == "llm_check":
            if llm_seen >= _MAX_LLM_CHECK:
                continue
            llm_seen += 1
        kept.append(c)
    return gates + kept[:_MAX_SCORED]


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


_CRITERION_TYPES_DOC = (
    "- min_length : params {min_chars: int} — longueur minimale attendue\n"
    "- keyword_presence : params {keywords: list[str]} — mots-clés devant apparaître\n"
    "- llm_check : params {description: str} — critère sémantique libre, vérifié par LLM\n"
    "- format_check : params {kind: str} — 'json' | 'code_block' | 'non_empty_lines'\n"
    "- references_tags : aucun param — la réponse doit référencer les tags requis\n"
)


def _build_prompt(task: Task, failure_context: FailureContext | None = None) -> str:
    context_section = f"# Contexte domaine\n{task.context}\n\n" if task.context else ""
    failure_section = ""
    if failure_context is not None:
        failed = [
            name for name, ok in failure_context.qa_result.criteria_results.items() if not ok
        ]
        failure_section = (
            "# Échec précédent\n"
            "Une spec précédente a jugé la réponse suivante comme un échec.\n"
            f"Réponse de l'agent:\n{failure_context.failed_output.content}\n\n"
            f"Verdict QA (score={failure_context.qa_result.score:.2f}): "
            f"{failure_context.qa_result.reason}\n"
            f"Critères ratés: {', '.join(failed) or 'aucun'}\n"
            f"Diagnostic: {failure_context.diagnostic_reason}\n"
            "Corrige la spec en conséquence : si les critères étaient inadaptés (trop "
            "stricts, hors-sujet), desserre-les ou remplace-les pour viser une évaluation "
            "juste de cette réponse.\n\n"
        )
    return (
        "Tu génères une EvaluatorSpec pour évaluer la réponse d'un agent à cette tâche.\n\n"
        f"# Tâche\n{task.description}\n\n"
        f"{context_section}"
        f"# Tags requis\n{', '.join(task.required_tags) or 'aucun'}\n\n"
        f"{failure_section}"
        "# Types de critères disponibles\n"
        f"{_CRITERION_TYPES_DOC}\n"
        "# Règles\n"
        "- Chaque critère porte un `type` (parmi la liste ci-dessus), une `importance` "
        "('critique' | 'normal' | 'mineur') et un `rationale` court (pourquoi ce critère).\n"
        "- Maximum 6 critères au total, dont au plus 4 de type 'llm_check'.\n"
        "- 'non_empty' est ajouté automatiquement comme unique gate — ne le déclare pas.\n"
        "- Utilise 'llm_check' pour les critères qualitatifs propres à cette tâche.\n"
        "- Ajoute un judge (mode 'rubric') si la tâche est complexe ou ambiguë.\n"
        "- Ne choisis PAS de seuil de succès : il est dérivé automatiquement."
    )


def build_llm_spec(
    task: Task,
    client: OpenAI,
    failure_context: FailureContext | None = None,
) -> EvaluatorSpec:
    """Génère un EvaluatorSpec via LLM (structured output).

    Moteur B (génération bornée) : caps déterministes, importance discrète,
    threshold dérivé, rationale. Moteur A (régénération informée) : si
    `failure_context` est fourni, le prompt inclut l'échec précédent.
    Fallback automatique sur build_adaptive_spec si le LLM échoue.
    """
    threshold = _derive_threshold(task)
    try:
        response = client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            temperature=0.0,
            messages=[
                {"role": "system", "content": "Tu produis une spec d'évaluation déclarative."},
                {"role": "user", "content": _build_prompt(task, failure_context)},
            ],
            response_format=_LLMEvaluatorSpec,
        )
        parsed = response.choices[0].message.parsed
        if parsed is None:
            raise ValueError("LLM returned no parsed _LLMEvaluatorSpec")
        spec = _filter_unknown_criteria(parsed.to_spec(), task)
        spec = spec.model_copy(update={"criteria": _apply_caps(list(spec.criteria))})
        spec = _ensure_non_empty_gate(spec)
        return spec.model_copy(update={"success_threshold": threshold})
    except Exception as e:
        logger.warning("build_llm_spec fallback to deterministic spec: %s", e)
        return build_adaptive_spec(task)
