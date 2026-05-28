from datetime import datetime, timezone
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel, ConfigDict

from aaosa.core.agent import Agent
from aaosa.qa.protocol import QAFailure, QAResult
from aaosa.qa.spec_evaluator import from_spec
from aaosa.qa.test_set import TestSet, active_cases
from aaosa.runtime.runner import run_task
from aaosa.schemas.output import Output
from aaosa.tracing.events import QAEvaluatedEvent
from aaosa.tracing.tracer import Tracer


class CaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str
    role: Literal["fix_target", "regression_guard"]
    n_runs: int
    pass_count: int
    pass_rate: float
    unstable: bool
    qa_results: list[QAResult]
    qa_failures: list[QAFailure]


class HealthCheckReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timestamp: datetime
    n_runs: int
    total_cases: int
    case_results: list[CaseResult]
    fix_target_pass_rate: float
    regression_guard_pass_rate: float
    unstable_cases: list[str]
    unattributed: list[str]


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def run_health_check(
    agents: list[Agent],
    test_set: TestSet,
    client: OpenAI,
    n_runs: int = 5,
    tracer: Tracer | None = None,
) -> HealthCheckReport:
    case_results: list[CaseResult] = []

    for case in active_cases(test_set):
        evaluator = from_spec(case.evaluator_spec, client=client, reference=case.reference)
        pass_count = 0
        qa_results: list[QAResult] = []
        qa_failures: list[QAFailure] = []

        for _ in range(n_runs):
            result = run_task(case.task, agents, client, tracer=tracer)  # mode V1, read-only ELO
            if not isinstance(result, Output):
                # DispatchResult ou QAFailure : compté comme run échoué
                continue
            qa = evaluator.evaluate(case.task, result)
            qa_results.append(qa)
            if tracer is not None:
                tracer.emit(QAEvaluatedEvent(
                    session_id=tracer.session_id, task_id=case.task.id,
                    agent_id=result.agent_id, success=qa.success,
                    score=qa.score, reason=qa.reason,
                ))
            if qa.success:
                pass_count += 1
            else:
                qa_failures.append(QAFailure(
                    task_id=case.task.id, agent_id=result.agent_id,
                    output=result, qa_result=qa,
                ))

        pass_rate = pass_count / n_runs if n_runs > 0 else 0.0
        case_results.append(CaseResult(
            task_id=case.task.id, role=case.role, n_runs=n_runs,
            pass_count=pass_count, pass_rate=pass_rate,
            unstable=0.4 <= pass_rate <= 0.6,
            qa_results=qa_results, qa_failures=qa_failures,
        ))

    guard_rates = [c.pass_rate for c in case_results if c.role == "regression_guard"]
    fix_rates = [c.pass_rate for c in case_results if c.role == "fix_target"]

    return HealthCheckReport(
        timestamp=datetime.now(timezone.utc),
        n_runs=n_runs,
        total_cases=len(case_results),
        case_results=case_results,
        fix_target_pass_rate=_mean(fix_rates),
        regression_guard_pass_rate=_mean(guard_rates),
        unstable_cases=[c.task_id for c in case_results if c.unstable],
        unattributed=[c.task.id for c in test_set.cases if c.attribution == "unattributed"],
    )
