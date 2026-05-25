from aaosa.core.agent import Agent
from aaosa.schemas.task import Task
from aaosa.schemas.elo import ELO_ACQUIRABLE_THRESHOLD


def passes_filter(agent: Agent, task: Task) -> bool:
    for tag, required_elo in task.required_tags.items():
        if required_elo <= ELO_ACQUIRABLE_THRESHOLD:
            continue  # acquirable tag — agent can pass Phase 1 without it
        if tag not in agent.tags_with_elo:
            return False
        if agent.tags_with_elo[tag] < required_elo:
            return False
    return True


def fit_score(agent: Agent, task: Task) -> float:
    total_agent = sum(agent.tags_with_elo.get(t, 0) for t in task.required_tags)
    total_required = sum(task.required_tags.values())
    return total_agent / total_required
