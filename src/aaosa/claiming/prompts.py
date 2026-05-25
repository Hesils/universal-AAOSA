from aaosa.core.agent import Agent
from aaosa.schemas.task import Task


def prompt_template(agent: Agent, task: Task) -> str:
    tags_lines = "\n".join(f"- {tag}: {elo}" for tag, elo in task.required_tags.items())
    return (
        f"{agent.system_prompt}\n\n"
        f"You are being asked to evaluate a task.\n\n"
        f"Task description:\n{task.description}\n\n"
        f"Required skills and minimum levels:\n{tags_lines}\n\n"
        f"Based on your capabilities, decide whether to claim this task.\n"
        f"Respond with your decision (claim or no_claim) and provide a justification."
    )
