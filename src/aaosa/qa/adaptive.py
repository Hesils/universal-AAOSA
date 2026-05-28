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
