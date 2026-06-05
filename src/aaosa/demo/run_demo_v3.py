"""Démo V3 runtime — incident de prod divisé, chaîne émergente, tool calls, B1.

Lancer : .venv\\Scripts\\python src\\aaosa\\demo\\run_demo_v3.py  (requiert OPENAI_API_KEY)
"""

from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from aaosa.demo.agents import DEMO_AGENTS
from aaosa.demo.tools import attach_tools
from aaosa.elo.persistence import save_snapshot
from aaosa.qa.spec_evaluator import AdaptiveSpecEvaluator
from aaosa.runtime.aggregator import TaskAggregator
from aaosa.runtime.context import RunContext
from aaosa.runtime.divider import TaskDivider
from aaosa.runtime.llm_client import create_client
from aaosa.runtime.runner import run_recovery
from aaosa.runtime.tagger import Tagger
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

_INCIDENT_CONTEXT = """\
# Incident report — checkout returns intermittent 500s under load
# api/middleware.py (auth on every request)
async def auth_middleware(request, call_next):
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    user = db.execute(f"SELECT * FROM users WHERE token='{token}'").fetchone()
    ...
# reporting/queries.py — p99 > 8s
SELECT u.name, COUNT(o.id) FROM users u, orders o
WHERE u.id = o.user_id GROUP BY u.id;  -- no index on FK columns
# 2M users / 15M orders, no index on users.token nor orders.user_id"""


def build_incident_task() -> Task:
    return Task(
        description=(
            "The checkout endpoint returns intermittent 500s under load. We suspect "
            "the auth middleware and a slow reporting SQL query. Investigate the root "
            "cause, fix it, and add a regression test."
        ),
        required_tags={"backend": 70, "python": 70, "database": 60},
        context=_INCIDENT_CONTEXT,
    )


def run_demo_v3() -> None:
    load_dotenv()
    client = create_client()
    runs_root = Path("runs")
    session_id = new_session_id()
    tracer = Tracer(session_id=session_id)
    started_at = datetime.now(timezone.utc)

    agents = list(DEMO_AGENTS)
    attach_tools(agents)
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

    task = build_incident_task()
    print("=== AAOSA Demo V3 — divided incident run ===\n")
    print(f"Input: {task.description}\n")

    result = run_recovery(task.description, ctx, pinned_tags=task.required_tags)
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
    run_demo_v3()
