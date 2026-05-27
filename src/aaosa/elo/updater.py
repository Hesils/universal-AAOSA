from pydantic import BaseModel, ConfigDict
from aaosa.core.agent import Agent
from aaosa.schemas.task import Task
from aaosa.schemas.elo import ELO_FLOOR, ELO_CEILING
from aaosa.elo.formula import compute_delta


class EloUpdateResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str
    task_id: str
    success: bool
    deltas: dict[str, int]
    acquired_tags: dict[str, int]
    elo_before: dict[str, int]
    elo_after: dict[str, int]


def update_agent_elo(agent: Agent, task: Task, success: bool) -> EloUpdateResult:
    elo_before = dict(agent.tags_with_elo)
    deltas: dict[str, int] = {}
    acquired_tags: dict[str, int] = {}

    for tag, required_elo in task.required_tags.items():
        old = agent.tags_with_elo[tag]
        delta = compute_delta(old, required_elo, success)
        agent.tags_with_elo[tag] = max(ELO_FLOOR, min(ELO_CEILING, old + delta))
        deltas[tag] = delta

    for tag, required_elo in task.acquirable_tags.items():
        if success:
            if tag not in agent.tags_with_elo:
                agent.tags_with_elo[tag] = required_elo
                acquired_tags[tag] = required_elo
            else:
                old = agent.tags_with_elo[tag]
                delta = compute_delta(old, required_elo, success)
                agent.tags_with_elo[tag] = max(ELO_FLOOR, min(ELO_CEILING, old + delta))
                deltas[tag] = delta
        else:
            if tag in agent.tags_with_elo:
                old = agent.tags_with_elo[tag]
                delta = compute_delta(old, required_elo, success)
                agent.tags_with_elo[tag] = max(ELO_FLOOR, min(ELO_CEILING, old + delta))
                deltas[tag] = delta

    return EloUpdateResult(
        agent_id=agent.id,
        task_id=task.id,
        success=success,
        deltas=deltas,
        acquired_tags=acquired_tags,
        elo_before=elo_before,
        elo_after=dict(agent.tags_with_elo),
    )
