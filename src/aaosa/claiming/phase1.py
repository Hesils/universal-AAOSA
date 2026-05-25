from aaosa.core.agent import Agent
from aaosa.schemas.task import Task
from aaosa.claiming.scoring import passes_filter, fit_score
from aaosa.tracing.tracer import Tracer
from aaosa.tracing.events import Phase1FilteredEvent


def filter_candidates(
    task: Task,
    agents: list[Agent],
    tracer: Tracer | None = None,
) -> list[tuple[Agent, float]]:
    candidates = []

    for agent in agents:
        score = fit_score(agent, task)
        passed = passes_filter(agent, task)

        if tracer is not None:
            tracer.emit(Phase1FilteredEvent(
                session_id=tracer.session_id,
                task_id=task.id,
                agent_id=agent.id,
                passed=passed,
                fit_score=score,
            ))

        if passed:
            candidates.append((agent, score))

    return candidates
