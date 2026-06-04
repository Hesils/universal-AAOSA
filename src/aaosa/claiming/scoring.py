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
    # Tags requis : toujours comptés. Tags acquérables : bonus pur, comptés
    # seulement si l'agent les possède — sinon un tag acquérable absent gonflerait
    # le dénominateur et pénaliserait qui ne l'a pas (Gap 2). required_tags est
    # non vide (invariant Task) → pas de division par zéro.
    counted = dict(task.required_tags)
    for tag, level in task.acquirable_tags.items():
        if tag in agent.tags_with_elo:
            counted[tag] = level
    total_agent = sum(agent.tags_with_elo.get(t, 0) for t in counted)
    total_required = sum(counted.values())
    return total_agent / total_required
