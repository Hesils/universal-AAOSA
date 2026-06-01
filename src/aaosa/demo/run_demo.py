from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from aaosa.demo.agents import DEMO_AGENTS
from aaosa.demo.tasks import DEMO_TASKS
from aaosa.elo.persistence import save_snapshot
from aaosa.qa.adaptive import build_adaptive_spec
from aaosa.qa.protocol import QAFailure
from aaosa.qa.spec_evaluator import from_spec
from aaosa.runtime.aggregator import TaskAggregator
from aaosa.runtime.divider import TaskDivider
from aaosa.runtime.llm_client import create_client
from aaosa.runtime.runner import run_divided_task, run_task
from aaosa.schemas.output import Output
from aaosa.schemas.task import Task
from aaosa.tracing.formatter import print_timeline
from aaosa.tracing.store import (
    SessionMeta,
    SessionTaskRecord,
    new_session_id,
    save_agent_registry,
    save_session,
)
from aaosa.tracing.tracer import Tracer


def run_demo() -> None:
    load_dotenv()
    client = create_client()
    runs_root = Path("runs")
    session_id = new_session_id()
    tracer = Tracer(session_id=session_id)
    started_at = datetime.now(timezone.utc)

    print("=== AAOSA Demo V2b ===\n")

    agent_by_id = {a.id: a for a in DEMO_AGENTS}
    task_records: list[SessionTaskRecord] = []

    for task in DEMO_TASKS:
        print(f"Task: {task.description}")
        spec = build_adaptive_spec(task)
        evaluator = from_spec(spec, client=client)
        judge_note = " (+judge)" if spec.judge else ""
        result = run_task(task, DEMO_AGENTS, client, tracer=tracer, evaluator=evaluator)
        if isinstance(result, Output):
            agent = agent_by_id[result.agent_id]
            print(f"  -> Assigned: {agent.name} (QA: PASS){judge_note}")
            outcome, winner_id = "qa_pass", result.agent_id
        elif isinstance(result, QAFailure):
            agent = agent_by_id[result.agent_id]
            print(f"  -> Assigned: {agent.name} (QA: FAIL - {result.qa_result.reason})")
            outcome, winner_id = "qa_fail", result.agent_id
        else:
            print(f"  -> Unassigned")
            outcome, winner_id = "unassigned", None
        task_records.append(SessionTaskRecord(
            id=task.id, description=task.description,
            winner_agent_id=winner_id, outcome=outcome,
            required_tags=task.required_tags,
            context=task.metadata.get("context") or None,
        ))
        print()

    # --- A4 : run divisé (TaskDivider + Aggregateur émergent) ---
    divider = TaskDivider(system_prompt=(
        "You are a task decomposer. Break a task into the minimal set of ordered "
        "sub-tasks needed to fully resolve it. Prefer few, well-scoped sub-tasks."
    ))
    aggregator = TaskAggregator(system_prompt=(
        "You are a synthesizer. Merge the sub-task results into one coherent, "
        "complete answer to the original task."
    ))
    divided_task = Task(
        description=(
            "Build a small REST API with a Python backend, a database layer, "
            "and a test suite covering the endpoints."
        ),
        required_tags={"python": 70, "backend": 70},
    )
    print(f"Divided task: {divided_task.description}")
    divided_result = run_divided_task(
        divided_task, DEMO_AGENTS, client, divider, aggregator, tracer=tracer
    )
    if isinstance(divided_result, Output):
        print("  -> Aggregated output produced (divided)")
        d_outcome, d_winner = "divided", None
    else:
        print(f"  -> Unassigned ({divided_result.reason})")
        d_outcome, d_winner = "unassigned", None
    task_records.append(SessionTaskRecord(
        id=divided_task.id, description=divided_task.description,
        winner_agent_id=d_winner, outcome=d_outcome,
        required_tags=divided_task.required_tags,
        context=None,
    ))
    print()

    print("=== Timeline ===")
    print_timeline(tracer.events)

    print("\n=== Persistence ===")
    save_agent_registry(DEMO_AGENTS, runs_root / "agents" / "registry.json")
    meta = SessionMeta(
        session_id=session_id,
        started_at=started_at,
        ended_at=datetime.now(timezone.utc),
        tasks=task_records,
        agent_ids=[a.id for a in DEMO_AGENTS],
    )
    session_dir = save_session(tracer, meta, runs_root, agents=DEMO_AGENTS)
    print(f"Session saved to {session_dir}")

    snapshot_dir = runs_root / "elo_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    path = save_snapshot(DEMO_AGENTS, snapshot_dir)
    print(f"ELO snapshot saved to {path}")


if __name__ == "__main__":
    run_demo()
