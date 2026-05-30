from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from aaosa.tracing.events import ExecutedEvent, QAEvaluatedEvent
from aaosa.tracing.store import AgentRegistry, SessionMeta, load_trace


class LatencyStats(BaseModel):
    model_config = ConfigDict(extra="forbid")
    count: int
    mean_ms: float | None
    min_ms: float | None
    max_ms: float | None


class PassRatePoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timestamp: datetime
    pass_rate: float


class InfraStats(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_count: int
    task_count: int
    agent_count: int
    run_count: int
    qa_pass_rate: float | None
    total_tokens_in: int
    total_tokens_out: int
    latency: LatencyStats
    pass_rate_over_time: list[PassRatePoint]


def collect(runs_root: Path) -> InfraStats:
    session_count = task_count = run_count = 0
    tokens_in = tokens_out = 0
    latencies: list[float] = []
    qa_total = qa_pass = 0
    pass_rate_over_time: list[PassRatePoint] = []
    agent_ids: set[str] = set()

    sdir = runs_root / "sessions"
    if sdir.exists():
        for d in sorted(sdir.iterdir()):
            meta_path, trace_path = d / "meta.json", d / "trace.jsonl"
            if not meta_path.exists() or not trace_path.exists():
                continue
            session_count += 1
            meta = SessionMeta.model_validate_json(meta_path.read_text(encoding="utf-8"))
            task_count += len(meta.tasks)
            agent_ids.update(meta.agent_ids)

            s_qa_total = s_qa_pass = 0
            for e in load_trace(trace_path):
                if isinstance(e, ExecutedEvent):
                    run_count += 1
                    if e.llm_metadata is not None:  # nullable -> skip si absent (S5)
                        tokens_in += e.llm_metadata.tokens_in
                        tokens_out += e.llm_metadata.tokens_out
                        latencies.append(e.llm_metadata.latency_ms)
                elif isinstance(e, QAEvaluatedEvent):
                    s_qa_total += 1
                    if e.success:
                        s_qa_pass += 1
            qa_total += s_qa_total
            qa_pass += s_qa_pass
            if s_qa_total > 0:
                pass_rate_over_time.append(PassRatePoint(timestamp=meta.started_at, pass_rate=s_qa_pass / s_qa_total))

    pass_rate_over_time.sort(key=lambda p: p.timestamp)

    reg_path = runs_root / "agents" / "registry.json"
    if reg_path.exists():
        reg = AgentRegistry.model_validate_json(reg_path.read_text(encoding="utf-8"))
        agent_ids.update(e.agent_id for e in reg.agents)

    return InfraStats(
        session_count=session_count,
        task_count=task_count,
        agent_count=len(agent_ids),
        run_count=run_count,
        qa_pass_rate=(qa_pass / qa_total) if qa_total > 0 else None,
        total_tokens_in=tokens_in,
        total_tokens_out=tokens_out,
        latency=LatencyStats(
            count=len(latencies),
            mean_ms=(sum(latencies) / len(latencies)) if latencies else None,
            min_ms=min(latencies) if latencies else None,
            max_ms=max(latencies) if latencies else None,
        ),
        pass_rate_over_time=pass_rate_over_time,
    )
