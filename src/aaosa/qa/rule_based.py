from aaosa.qa.protocol import QAResult
from aaosa.schemas.output import Output
from aaosa.schemas.task import Task


class BasicRuleEvaluator:
    def evaluate(self, task: Task, output: Output) -> QAResult:
        criteria: dict[str, bool] = {}

        criteria["non_empty"] = len(output.content) > 0
        criteria["min_length"] = len(output.content) >= 50

        content_lower = output.content.lower()
        criteria["references_tags"] = all(
            tag.lower() in content_lower
            for tag in task.required_tags
        )

        passed = sum(1 for v in criteria.values() if v)
        total = len(criteria)
        score = passed / total if total > 0 else 0.0
        success = all(criteria.values())

        return QAResult(
            task_id=task.id,
            agent_id=output.agent_id,
            success=success,
            score=score,
            reason="All criteria met" if success else "Some criteria failed",
            criteria_results=criteria,
        )
