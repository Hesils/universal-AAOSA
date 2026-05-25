from openai import OpenAI

from aaosa.claiming.dispatch import DispatchResult, dispatch
from aaosa.claiming.phase1 import filter_candidates
from aaosa.claiming.phase2 import run_phase2
from aaosa.core.agent import Agent
from aaosa.schemas.output import Output
from aaosa.schemas.task import Task
from aaosa.tracing.events import ExecutedEvent
from aaosa.tracing.tracer import Tracer


def run_task(
    task: Task,
    agents: list[Agent],
    client: OpenAI,
    tracer: Tracer | None = None,
) -> Output | DispatchResult:
    candidates = filter_candidates(task, agents, tracer)
    fit_scores = {agent.id: score for agent, score in candidates}
    claims = run_phase2(task, candidates, client, tracer)

    candidate_agents = [agent for agent, _ in candidates]
    result = dispatch(claims, task, candidate_agents, fit_scores, tracer)

    if result.status == "unassigned":
        return result

    agent_map = {agent.id: agent for agent in candidate_agents}
    winner = agent_map[result.agent_id]
    output = winner.execute(task, client)

    if tracer is not None:
        tracer.emit(ExecutedEvent(
            session_id=tracer.session_id,
            task_id=task.id,
            agent_id=winner.id,
            output_summary=output.content[:100],
        ))

    return output
