from aaosa.qa.adaptive import build_llm_spec
from aaosa.qa.diagnostic import FailureContext
from aaosa.qa.criteria import get_criterion
from aaosa.runtime.providers import LLMProvider
from aaosa.qa.judge import JudgeBreakdown, run_judge
from aaosa.qa.protocol import QAResult
from aaosa.qa.spec import EvaluatorSpec
from aaosa.schemas.output import Output
from aaosa.schemas.task import Task


def _criteria_keys(criteria) -> list[str]:
    """Clé unique par critère : `name` si unique, `name#k` (k ordinal) si homonymes."""
    totals: dict[str, int] = {}
    for c in criteria:
        totals[c.name] = totals.get(c.name, 0) + 1
    seen: dict[str, int] = {}
    keys: list[str] = []
    for c in criteria:
        if totals[c.name] == 1:
            keys.append(c.name)
        else:
            seen[c.name] = seen.get(c.name, 0) + 1
            keys.append(f"{c.name}#{seen[c.name]}")
    return keys


class SpecEvaluator:
    def __init__(
        self,
        spec: EvaluatorSpec,
        client: LLMProvider | None = None,
        reference: str | None = None,
        model: str | None = None,
    ):
        needs_client = spec.judge is not None or any(
            c.name == "llm_check" for c in spec.criteria
        )
        if needs_client and client is None:
            raise ValueError("spec needs a client (judge or llm_check) but none was provided")
        self.spec = spec
        self.provider = client
        self.reference = reference
        self.model = model

    def evaluate(self, task: Task, output: Output) -> QAResult:
        criteria_results: dict[str, bool] = {}
        keys = _criteria_keys(self.spec.criteria)
        keyed = list(zip(self.spec.criteria, keys))

        # 1. Gates (ordre de la spec)
        for c, key in keyed:
            if not c.gate:
                continue
            outcome = get_criterion(c.name)(task, output, {**c.params, "provider": self.provider, "model": self.model})
            criteria_results[key] = outcome.passed
            if not outcome.passed:
                return QAResult(
                    task_id=task.id, agent_id=output.agent_id,
                    success=False, score=0.0,
                    reason=f"gate failed: {c.name} ({outcome.detail})",
                    criteria_results=criteria_results,
                )

        # 2. Critères scorés
        scored = [(c, key) for c, key in keyed if not c.gate]
        if scored:
            total_weight = sum(c.weight for c, _ in scored)
            weighted = 0.0
            for c, key in scored:
                outcome = get_criterion(c.name)(task, output, {**c.params, "provider": self.provider, "model": self.model})
                criteria_results[key] = outcome.passed
                weighted += outcome.score * c.weight
            det_score = weighted / total_weight if total_weight > 0 else 1.0
        else:
            det_score = 1.0

        # 3. Judge
        reason = "deterministic criteria evaluated"
        judge_breakdown: JudgeBreakdown | None = None
        if self.spec.judge is not None:
            judge_result = run_judge(
                task, output, self.spec.judge, self.provider, self.reference
            )
            w = self.spec.judge.weight
            final = (1.0 - w) * det_score + w * judge_result.overall
            reason = f"det={det_score:.2f} judge={judge_result.overall:.2f} ({judge_result.reason})"
            judge_breakdown = JudgeBreakdown(
                mode=self.spec.judge.mode,
                overall=judge_result.overall,
                dimension_scores=judge_result.dimension_scores,
                reason=judge_result.reason,
            )
        else:
            final = det_score

        # 4. Verdict
        return QAResult(
            task_id=task.id, agent_id=output.agent_id,
            success=final >= self.spec.success_threshold,
            score=final, reason=reason, criteria_results=criteria_results,
            judge=judge_breakdown,
            spec_used=self.spec,
        )


def from_spec(
    spec: EvaluatorSpec,
    client: LLMProvider | None = None,
    reference: str | None = None,
    model: str | None = None,
) -> SpecEvaluator:
    return SpecEvaluator(spec, client=client, reference=reference, model=model)


class AdaptiveSpecEvaluator:
    """Evaluator paresseux : génère la spec par tâche (B1) dans evaluate.

    Satisfait le Protocol QAEvaluator. `failure_context` optionnel (D4 moteur A) :
    s'il est fourni, build_llm_spec régénère une spec informée par l'échec.
    """

    def __init__(self, client: LLMProvider, failure_context: FailureContext | None = None, model: str | None = None):
        self.provider = client
        self.failure_context = failure_context
        self.model = model

    def evaluate(self, task: Task, output: Output) -> QAResult:
        spec = build_llm_spec(task, self.provider, self.failure_context, model=self.model)
        return SpecEvaluator(spec, client=self.provider, model=self.model).evaluate(task, output)
