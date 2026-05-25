from openai import OpenAI

from aaosa.core.agent import Agent
from aaosa.schemas.claim import Claim
from aaosa.schemas.task import Task
from aaosa.tracing.events import Phase2ClaimedEvent
from aaosa.tracing.tracer import Tracer


def collect_claims(
    task: Task,
    candidates: list[tuple[Agent, float]],
    client: OpenAI,
    tracer: Tracer | None = None,
) -> list[Claim]:
    results: list[Claim] = []

    for agent, _ in candidates:
        claim = agent.claim(task, client)

        if tracer is not None:
            tracer.emit(Phase2ClaimedEvent(
                session_id=tracer.session_id,
                task_id=task.id,
                agent_id=agent.id,
                decision=claim.decision,
                justification=claim.justification,
            ))

        results.append(claim)

    return results
