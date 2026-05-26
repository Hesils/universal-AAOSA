from dotenv import load_dotenv

from aaosa.claiming.dispatch import DispatchResult
from aaosa.demo.agents import DEMO_AGENTS
from aaosa.demo.tasks import DEMO_TASKS
from aaosa.runtime.llm_client import create_client
from aaosa.runtime.runner import run_task
from aaosa.schemas.output import Output
from aaosa.tracing.formatter import print_timeline
from aaosa.tracing.tracer import Tracer


def run_demo() -> None:
    load_dotenv()
    client = create_client()
    tracer = Tracer(session_id="demo")

    print("=== AAOSA Demo ===\n")

    agent_by_id = {a.id: a for a in DEMO_AGENTS}

    for task in DEMO_TASKS:
        print(f"Task: {task.description}")
        result = run_task(task, DEMO_AGENTS, client, tracer)
        if isinstance(result, Output):
            agent = agent_by_id[result.agent_id]
            print(f"  → Assigned: {agent.name}")
        else:
            print(f"  → Unassigned")
        print()

    print("=== Timeline ===")
    print_timeline(tracer.events)


if __name__ == "__main__":
    run_demo()
