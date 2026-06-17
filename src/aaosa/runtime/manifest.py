# src/aaosa/runtime/manifest.py
"""Manifest d'un run `solve` — fonction PURE dérivée de la trace + résultat.

Post-hoc (suit classify_run, respecte « tracer = observer découplé »). Le runtime
n'imprime/ne juge jamais lui-même. tool-calls « déclarés » (ToolCalledEvent), pas
FS-diff des effets réels (plus tard, lié v1m). roster_gap = signal (création d'agent
côté AIOS), pas un bug.
"""

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from aaosa.claiming.dispatch import DispatchResult
from aaosa.qa.protocol import QAFailure
from aaosa.schemas.output import Output
from aaosa.tracing.analysis import classify_run
from aaosa.tracing.events import (
    ClaimEvent,
    ExecutedEvent,
    RosterGapEvent,
    TaskAggregatedEvent,
    ToolCalledEvent,
)


class ToolCallRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: str
    tool_name: str
    arguments: dict
    result: str


class FinalOutputRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str
    agent_id: str
    content: str


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: str
    typologies: list[str]
    final_outputs: list[FinalOutputRecord]
    tool_calls: list[ToolCallRecord]
    roster_gaps: list[str]
    trace_path: str


def _outcome(result: Output | DispatchResult | QAFailure) -> str:
    """Même vocabulaire que cli.incident_runs._result_kind (success|qa_fail|unassigned)."""
    if isinstance(result, Output):
        return "success"
    if isinstance(result, QAFailure):
        return "qa_fail"
    if result.status == "qa_failed":
        return "qa_fail"
    return "unassigned"


def _final_outputs(
    events: Sequence[ClaimEvent], result: Output | DispatchResult | QAFailure
) -> list[FinalOutputRecord]:
    if isinstance(result, Output):
        return [FinalOutputRecord(task_id=result.task_id, agent_id=result.agent_id, content=result.content)]
    # Run divisé / agrégé : dernier event porteur de contenu terminal dans la trace.
    for e in reversed(list(events)):
        if isinstance(e, TaskAggregatedEvent):
            return [FinalOutputRecord(task_id=e.task_id, agent_id="aggregator", content=e.output_content)]
        if isinstance(e, ExecutedEvent) and e.output_content is not None:
            return [FinalOutputRecord(task_id=e.task_id, agent_id=e.agent_id, content=e.output_content)]
    return []


def build_manifest(
    events: Sequence[ClaimEvent],
    result: Output | DispatchResult | QAFailure,
    trace_path: str,
) -> Manifest:
    """Dérive le manifest de la trace + résultat. Aucune I/O (la persistance est au caller)."""
    roster_gaps: list[str] = []
    for e in events:
        if isinstance(e, RosterGapEvent):
            roster_gaps.extend(e.missing_tags)
    tool_calls = [
        ToolCallRecord(agent_id=e.agent_id, tool_name=e.tool_name, arguments=e.arguments, result=e.result)
        for e in events
        if isinstance(e, ToolCalledEvent)
    ]
    return Manifest(
        outcome=_outcome(result),
        typologies=classify_run(events),
        final_outputs=_final_outputs(events, result),
        tool_calls=tool_calls,
        roster_gaps=roster_gaps,
        trace_path=trace_path,
    )
