from pydantic import BaseModel, ConfigDict, Field
from aaosa.core.agent import Agent
from aaosa.schemas.task import Task
from aaosa.schemas.elo import ELO_FLOOR, ELO_CEILING, ELO_TAG_LOSS_THRESHOLD
from aaosa.elo.formula import compute_delta


class EloUpdateResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str
    task_id: str
    success: bool
    deltas: dict[str, int]
    acquired_tags: dict[str, int]
    lost_tags: dict[str, int] = Field(default_factory=dict)
    elo_before: dict[str, int]
    elo_after: dict[str, int]


def _apply_delta(
    agent: Agent,
    tag: str,
    old: int,
    delta: int,
    lost_tags: dict[str, int],
) -> None:
    """Apply a computed delta to a tag the agent already holds.

    Mirror of acquisition: if the raw post-delta ELO drops strictly below
    ELO_TAG_LOSS_THRESHOLD (the floor is deliberately ignored), the agent
    loses the tag entirely. Otherwise the new ELO is clamped to
    [ELO_FLOOR, ELO_CEILING].
    """
    raw = old + delta
    if raw < ELO_TAG_LOSS_THRESHOLD:
        del agent.tags_with_elo[tag]
        lost_tags[tag] = old
    else:
        agent.tags_with_elo[tag] = max(ELO_FLOOR, min(ELO_CEILING, raw))


def update_agent_elo(agent: Agent, task: Task, success: bool) -> EloUpdateResult:
    elo_before = dict(agent.tags_with_elo)
    deltas: dict[str, int] = {}
    acquired_tags: dict[str, int] = {}
    lost_tags: dict[str, int] = {}

    for tag, required_elo in task.required_tags.items():
        old = agent.tags_with_elo[tag]
        delta = compute_delta(old, required_elo, success)
        deltas[tag] = delta
        _apply_delta(agent, tag, old, delta, lost_tags)

    for tag, required_elo in task.acquirable_tags.items():
        if success:
            if tag not in agent.tags_with_elo:
                agent.tags_with_elo[tag] = required_elo
                acquired_tags[tag] = required_elo
            else:
                old = agent.tags_with_elo[tag]
                delta = compute_delta(old, required_elo, success)
                deltas[tag] = delta
                _apply_delta(agent, tag, old, delta, lost_tags)
        else:
            if tag in agent.tags_with_elo:
                old = agent.tags_with_elo[tag]
                delta = compute_delta(old, required_elo, success)
                deltas[tag] = delta
                _apply_delta(agent, tag, old, delta, lost_tags)

    return EloUpdateResult(
        agent_id=agent.id,
        task_id=task.id,
        success=success,
        deltas=deltas,
        acquired_tags=acquired_tags,
        lost_tags=lost_tags,
        elo_before=elo_before,
        elo_after=dict(agent.tags_with_elo),
    )
