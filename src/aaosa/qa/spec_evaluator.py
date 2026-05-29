from openai import OpenAI

from aaosa.qa.criteria import get_criterion
from aaosa.qa.judge import JudgeBreakdown, run_judge
from aaosa.qa.protocol import QAResult
from aaosa.qa.spec import EvaluatorSpec
from aaosa.schemas.output import Output
from aaosa.schemas.task import Task


class SpecEvaluator:
    def __init__(
        self,
        spec: EvaluatorSpec,
        client: OpenAI | None = None,
        reference: str | None = None,
    ):
        if spec.judge is not None and client is None:
            raise ValueError("spec has a judge but no client was provided")
        self.spec = spec
        self.client = client
        self.reference = reference

    def evaluate(self, task: Task, output: Output) -> QAResult:
        criteria_results: dict[str, bool] = {}

        # 1. Gates (ordre de la spec)
        for c in self.spec.criteria:
            if not c.gate:
                continue
            outcome = get_criterion(c.name)(task, output, c.params)
            criteria_results[outcome.name] = outcome.passed
            if not outcome.passed:
                return QAResult(
                    task_id=task.id, agent_id=output.agent_id,
                    success=False, score=0.0,
                    reason=f"gate failed: {c.name} ({outcome.detail})",
                    criteria_results=criteria_results,
                )

        # 2. Critères scorés
        scored = [c for c in self.spec.criteria if not c.gate]
        if scored:
            total_weight = sum(c.weight for c in scored)
            weighted = 0.0
            for c in scored:
                outcome = get_criterion(c.name)(task, output, c.params)
                criteria_results[outcome.name] = outcome.passed
                weighted += outcome.score * c.weight
            det_score = weighted / total_weight if total_weight > 0 else 1.0
        else:
            det_score = 1.0

        # 3. Judge
        reason = "deterministic criteria evaluated"
        judge_breakdown: JudgeBreakdown | None = None
        if self.spec.judge is not None:
            judge_result = run_judge(
                task, output, self.spec.judge, self.client, self.reference
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
        )


def from_spec(
    spec: EvaluatorSpec,
    client: OpenAI | None = None,
    reference: str | None = None,
) -> SpecEvaluator:
    return SpecEvaluator(spec, client=client, reference=reference)
