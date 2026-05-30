from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

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
    session_dir = save_session(tracer, meta, runs_root)
    print(f"Session saved to {session_dir}")

    snapshot_dir = runs_root / "elo_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    path = save_snapshot(DEMO_AGENTS, snapshot_dir)
    print(f"ELO snapshot saved to {path}")


if __name__ == "__main__":
    run_demo()
