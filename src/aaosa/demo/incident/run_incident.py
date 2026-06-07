"""Script de validation jetable — démo incident phase 3 (remplacé par le CLI phase 4).

Lancer : .venv\\Scripts\\python src\\aaosa\\demo\\incident\\run_incident.py [main|roster_gap]
(requiert OPENAI_API_KEY dans .env)
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from aaosa.demo.incident.scenarios import (
    build_data_leak_task,
    full_roster,
    roster_gap_roster,
)
from aaosa.elo.persistence import save_snapshot
from aaosa.qa.spec_evaluator import AdaptiveSpecEvaluator
from aaosa.runtime.aggregator import TaskAggregator
from aaosa.runtime.context import RunContext
from aaosa.runtime.divider import TaskDivider
from aaosa.runtime.llm_client import create_client
from aaosa.runtime.runner import run_with_recovery
from aaosa.runtime.tagger import Tagger
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

_ROSTERS = {"main": full_roster, "roster_gap": roster_gap_roster}


def run_incident(scenario: str) -> None:
    load_dotenv()
    client = create_client()
    runs_root = Path("runs")
    session_id = new_session_id()
    tracer = Tracer(session_id=session_id)
    started_at = datetime.now(timezone.utc)

    agents = _ROSTERS[scenario]()
    evaluator = AdaptiveSpecEvaluator(client)

    divider = TaskDivider(system_prompt=(
        "You are a task decomposer. Break the task into the minimal set of ordered "
        "sub-tasks needed to fully resolve it. Express dependencies between sub-tasks. "
        "Prefer few, well-scoped sub-tasks, and include a final synthesis sub-task."
    ))
    aggregator = TaskAggregator(system_prompt=(
        "You are a synthesizer. Merge the sub-task results into one coherent, complete "
        "answer to the original incident."
    ))
    tagger = Tagger(system_prompt=(
        "You assign capability tags to a task description. Use the roster vocabulary "
        "when it fits; name a real capability even if absent. Return at least one tag."
    ))
    ctx = RunContext(
        agents=agents, client=client, divider=divider, aggregator=aggregator,
        tagger=tagger, tracer=tracer, evaluator=evaluator,
    )

    task = build_data_leak_task()
    print(f"=== AAOSA incident demo — scenario: {scenario} ({len(agents)} agents) ===\n")
    print(f"Input: {task.description}\n")

    # run_with_recovery directement : jamais de division forcée (thèse D1),
    # et la Task du meta EST la racine de la trace.
    result = run_with_recovery(task, ctx)
    outcome = "divided" if isinstance(result, Output) else "unassigned"
    print(f"  -> {outcome}\n")

    print("=== Timeline ===")
    print_timeline(tracer.events)

    print("\n=== Persistence ===")
    save_agent_registry(agents, runs_root / "agents" / "registry.json")
    meta = SessionMeta(
        session_id=session_id,
        started_at=started_at,
        ended_at=datetime.now(timezone.utc),
        tasks=[SessionTaskRecord(
            id=task.id, description=task.description,
            winner_agent_id=None, outcome=outcome,
            required_tags=task.required_tags, context=task.context,
        )],
        agent_ids=[a.id for a in agents],
    )
    session_dir = save_session(tracer, meta, runs_root, agents=agents)
    print(f"Session saved to {session_dir}")

    snapshot_dir = runs_root / "elo_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    path = save_snapshot(agents, snapshot_dir)
    print(f"ELO snapshot saved to {path}")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "main"
    if arg not in _ROSTERS:
        sys.exit(f"Usage: run_incident.py [main|roster_gap] (got {arg!r})")
    run_incident(arg)
