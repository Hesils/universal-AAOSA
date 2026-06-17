import asyncio

from aaosa.core.agent import Agent
from aaosa.runtime.providers import LLMProvider
from aaosa.schemas.claim import Claim
from aaosa.schemas.task import Task
from aaosa.tracing.events import Phase2ClaimedEvent
from aaosa.tracing.tracer import Tracer


def collect_claims(
    task: Task,
    candidates: list[tuple[Agent, float]],
    provider: LLMProvider,
    tracer: Tracer | None = None,
) -> list[Claim]:
    results: list[Claim] = []

    for agent, _ in candidates:
        claim = agent.claim(task, provider)

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


def run_phase2(
    task: Task,
    candidates: list[tuple[Agent, float]],
    provider: LLMProvider,
    tracer: Tracer | None = None,
) -> list[Claim]:
    results: list[Claim] = []

    for agent, _ in candidates:
        for _ in range(2):
            try:
                claim = agent.claim(task, provider)
                if tracer is not None:
                    tracer.emit(Phase2ClaimedEvent(
                        session_id=tracer.session_id,
                        task_id=task.id,
                        agent_id=agent.id,
                        decision=claim.decision,
                        justification=claim.justification,
                    ))
                results.append(claim)
                break
            except Exception:
                pass

    return results


async def run_phase2_async(
    task: Task,
    candidates: list[tuple[Agent, float]],
    provider: LLMProvider,
    tracer: Tracer | None = None,
) -> list[Claim]:
    async def _claim_agent(agent: Agent) -> Claim | None:
        for _ in range(2):
            try:
                claim = await asyncio.to_thread(agent.claim, task, provider)
                if tracer is not None:
                    tracer.emit(Phase2ClaimedEvent(
                        session_id=tracer.session_id,
                        task_id=task.id,
                        agent_id=agent.id,
                        decision=claim.decision,
                        justification=claim.justification,
                    ))
                return claim
            except Exception:
                pass
        return None

    raw = await asyncio.gather(*(_claim_agent(a) for a, _ in candidates))
    return [c for c in raw if c is not None]
