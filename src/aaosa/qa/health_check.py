from datetime import datetime, timezone

from openai import OpenAI
from pydantic import BaseModel, ConfigDict

from aaosa.claiming.dispatch import DispatchResult
from aaosa.core.agent import Agent
from aaosa.qa.protocol import QAEvaluator, QAFailure, QAResult
from aaosa.runtime.runner import run_task
from aaosa.schemas.task import Task
from aaosa.tracing.events import QAEvaluatedEvent
from aaosa.tracing.tracer import Tracer

TestCase = tuple[Task, QAEvaluator]


class HealthCheckReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timestamp: datetime
    total_tasks: int
    passed: int
    failed: int
    skipped: int
    qa_results: list[QAResult]
    qa_failures: list[QAFailure]


def run_health_check(
    agents: list[Agent],
    test_suite: list[TestCase],
    client: OpenAI,
    tracer: Tracer | None = None,
) -> HealthCheckReport:
    passed = 0
    failed = 0
    skipped = 0
    qa_results: list[QAResult] = []
    qa_failures: list[QAFailure] = []

    for task, evaluator in test_suite:
        result = run_task(task, agents, client, tracer=tracer)

        if isinstance(result, DispatchResult):
            skipped += 1
            continue

        output = result
        qa_result = evaluator.evaluate(task, output)
        qa_results.append(qa_result)

        if tracer is not None:
            tracer.emit(QAEvaluatedEvent(
                session_id=tracer.session_id,
                task_id=task.id,
                agent_id=output.agent_id,
                success=qa_result.success,
                score=qa_result.score,
                reason=qa_result.reason,
            ))

        if qa_result.success:
            passed += 1
        else:
            failed += 1
            qa_failures.append(QAFailure(
                task_id=task.id,
                agent_id=output.agent_id,
                output=output,
                qa_result=qa_result,
            ))

    return HealthCheckReport(
        timestamp=datetime.now(timezone.utc),
        total_tasks=passed + failed + skipped,
        passed=passed,
        failed=failed,
        skipped=skipped,
        qa_results=qa_results,
        qa_failures=qa_failures,
    )
