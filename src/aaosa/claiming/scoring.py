from aaosa.core.agent import Agent
from aaosa.schemas.task import Task


def passes_filter(agent: Agent, task: Task) -> bool:
    for tag, required_elo in task.required_tags.items():
        if tag not in agent.tags_with_elo:
            return False
        if agent.tags_with_elo[tag] < required_elo:
            return False
    return True


def fit_score(agent: Agent, task: Task) -> float:
    all_tags = {**task.required_tags, **task.acquirable_tags}
    total_agent = sum(agent.tags_with_elo.get(t, 0) for t in all_tags)
    total_required = sum(all_tags.values())
    return total_agent / total_required
