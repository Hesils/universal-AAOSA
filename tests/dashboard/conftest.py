from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from aaosa.demo.agents import DEMO_AGENTS
from aaosa.demo.tasks import DEMO_TASKS
from aaosa.elo.persistence import AgentEloSnapshot, EloSnapshot
from aaosa.qa.health_check import CaseResult, HealthCheckReport, save_health_check
from aaosa.qa.protocol import QAResult
from aaosa.qa.spec import CriterionSpec, EvaluatorSpec
from aaosa.qa.test_set import TestCase, TestSet
from aaosa.schemas.output import LLMMetadata
from aaosa.tracing.events import (
    DispatchedEvent,
    EloUpdatedEvent,
    ExecutedEvent,
    Phase1FilteredEvent,
    Phase2ClaimedEvent,
    QAEvaluatedEvent,
    UnassignedEvent,
)
from aaosa.tracing.store import (
    SessionMeta,
    SessionTaskRecord,
    save_agent_registry,
    save_session,
)
from aaosa.tracing.tracer import Tracer


@pytest.fixture
def runs_root(tmp_path) -> Path:
    root = tmp_path / "runs"
    root.mkdir()
    a0, a1 = DEMO_AGENTS[0], DEMO_AGENTS[1]
    t0, t1 = DEMO_TASKS[0], DEMO_TASKS[1]
    lm = LLMMetadata(model_name="gpt-4o-mini", tokens_in=120, tokens_out=80, latency_ms=350.0)

    # --- agents/registry.json ---
    save_agent_registry(DEMO_AGENTS, root / "agents" / "registry.json")

    # --- elo_snapshots : deux timestamps -> historique par tag ---
    snap_dir = root / "elo_snapshots"
    snap_dir.mkdir()
    base = datetime(2026, 5, 30, 10, 0, 0, tzinfo=timezone.utc)
    for i, ts in enumerate([base, base + timedelta(hours=1)]):
        snap = EloSnapshot(
            timestamp=ts,
            agents=[
                AgentEloSnapshot(
                    agent_name=a.name,
                    agent_id=a.id,
                    tags_with_elo={tag: elo + i * 3 for tag, elo in a.tags_with_elo.items()},
                )
                for a in DEMO_AGENTS
            ],
        )
        data = snap.model_dump_json(indent=2)
        (snap_dir / (ts.strftime("%Y-%m-%dT%H-%M-%S") + ".json")).write_text(data, encoding="utf-8")
        if i == 1:
            (snap_dir / "latest.json").write_text(data, encoding="utf-8")

    # --- session : t0 qa_pass (a0 gagne), t1 unassigned ---
    sid = "2026-05-30T10-00-00-aaaa"
    tracer = Tracer(session_id=sid)
    tracer.emit(Phase1FilteredEvent(session_id=sid, task_id=t0.id, agent_id=a0.id, passed=True, fit_score=0.9))
    tracer.emit(Phase1FilteredEvent(session_id=sid, task_id=t0.id, agent_id=a1.id, passed=False, fit_score=0.2))
    tracer.emit(Phase2ClaimedEvent(session_id=sid, task_id=t0.id, agent_id=a0.id, decision="claim", justification="mine"))
    tracer.emit(DispatchedEvent(session_id=sid, task_id=t0.id, agent_id=a0.id, reason="best fit"))
    tracer.emit(ExecutedEvent(session_id=sid, task_id=t0.id, agent_id=a0.id, output_summary="done", output_content="full output body", llm_metadata=lm))
    tracer.emit(QAEvaluatedEvent(session_id=sid, task_id=t0.id, agent_id=a0.id, success=True, score=0.85, reason="good", criteria_results={"non_empty": True}))
    tracer.emit(EloUpdatedEvent(session_id=sid, task_id=t0.id, agent_id=a0.id, deltas={list(t0.required_tags)[0]: 5}))
    tracer.emit(Phase1FilteredEvent(session_id=sid, task_id=t1.id, agent_id=a0.id, passed=False, fit_score=0.1))
    tracer.emit(UnassignedEvent(session_id=sid, task_id=t1.id, reason="no capable agent"))

    meta = SessionMeta(
        session_id=sid,
        started_at=base,
        ended_at=base + timedelta(minutes=2),
        tasks=[
            SessionTaskRecord(id=t0.id, description=t0.description, winner_agent_id=a0.id, outcome="qa_pass", required_tags=t0.required_tags),
            SessionTaskRecord(id=t1.id, description=t1.description, winner_agent_id=None, outcome="unassigned", required_tags=t1.required_tags),
        ],
        agent_ids=[a.id for a in DEMO_AGENTS],
    )
    save_session(tracer, meta, root)

    # --- health check : 1 cas actif (regression_guard/agent) + 1 quarantaine (fix_target/task_spec) ---
    hc_ts = datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc)
    spec = EvaluatorSpec(criteria=[CriterionSpec(name="non_empty", gate=True)])
    test_set = TestSet(cases=[
        TestCase(task=t0, evaluator_spec=spec, origin="curated", role="regression_guard", attribution="agent"),
        TestCase(task=t1, evaluator_spec=spec, origin="runtime_failure", role="fix_target", attribution="task_spec"),
    ])
    qa = QAResult(task_id=t0.id, agent_id=a0.id, success=True, score=0.9, reason="ok", criteria_results={"non_empty": True})
    case_result = CaseResult(
        task_id=t0.id, role="regression_guard", n_runs=3, pass_count=2, pass_rate=2 / 3,
        unstable=False, qa_results=[qa, qa], qa_failures=[],
    )
    report = HealthCheckReport(
        timestamp=hc_ts, n_runs=3, total_cases=1, case_results=[case_result],
        fix_target_pass_rate=0.0, regression_guard_pass_rate=2 / 3,
        unstable_cases=[], unattributed=[], task_spec_quarantined=[t1.id], evaluator_quarantined=[],
    )
    hc_tracer = Tracer(session_id="hc-" + sid)
    hc_tracer.emit(Phase1FilteredEvent(session_id=hc_tracer.session_id, task_id=t0.id, agent_id=a0.id, passed=True, fit_score=0.9))
    hc_tracer.emit(DispatchedEvent(session_id=hc_tracer.session_id, task_id=t0.id, agent_id=a0.id, reason="best fit"))
    hc_tracer.emit(ExecutedEvent(session_id=hc_tracer.session_id, task_id=t0.id, agent_id=a0.id, output_summary="done", output_content="hc body", llm_metadata=lm))
    hc_tracer.emit(QAEvaluatedEvent(session_id=hc_tracer.session_id, task_id=t0.id, agent_id=a0.id, success=True, score=0.9, reason="ok", criteria_results={"non_empty": True}))
    save_health_check(report, test_set, hc_tracer, root / "health_checks")

    return root
