from pathlib import Path

from dotenv import load_dotenv

from aaosa.claiming.dispatch import DispatchResult
from aaosa.demo.agents import DEMO_AGENTS
from aaosa.demo.tasks import DEMO_TASKS
from aaosa.elo.persistence import save_snapshot
from aaosa.qa.adaptive import build_adaptive_spec
from aaosa.qa.protocol import QAFailure
from aaosa.qa.spec_evaluator import from_spec
from aaosa.runtime.llm_client import create_client
from aaosa.runtime.runner import run_task
from aaosa.schemas.output import Output
from aaosa.tracing.formatter import print_timeline
from aaosa.tracing.tracer import Tracer


def run_demo() -> None:
    load_dotenv()
    client = create_client()
    tracer = Tracer(session_id="demo")

    print("=== AAOSA Demo V2b ===\n")

    agent_by_id = {a.id: a for a in DEMO_AGENTS}

    for task in DEMO_TASKS:
        print(f"Task: {task.description}")
        spec = build_adaptive_spec(task)
        evaluator = from_spec(spec, client=client)
        judge_note = " (+judge)" if spec.judge else ""
        result = run_task(task, DEMO_AGENTS, client, tracer=tracer, evaluator=evaluator)
        if isinstance(result, Output):
            agent = agent_by_id[result.agent_id]
            print(f"  -> Assigned: {agent.name} (QA: PASS){judge_note}")
        elif isinstance(result, QAFailure):
            agent = agent_by_id[result.agent_id]
            print(f"  -> Assigned: {agent.name} (QA: FAIL - {result.qa_result.reason})")
        else:
            print(f"  -> Unassigned")
        print()

    print("=== Timeline ===")
    print_timeline(tracer.events)

    print("\n=== ELO Snapshot ===")
    snapshot_dir = Path("elo_snapshots")
    snapshot_dir.mkdir(exist_ok=True)
    path = save_snapshot(DEMO_AGENTS, snapshot_dir)
    print(f"Saved to {path}")


if __name__ == "__main__":
    run_demo()
