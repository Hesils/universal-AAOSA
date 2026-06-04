from aaosa.tracing.events import (
    ClaimEvent,
    Phase1FilteredEvent,
    Phase2ClaimedEvent,
    DispatchedEvent,
    ExecutedEvent,
    UnassignedEvent,
    QAEvaluatedEvent,
    EloUpdatedEvent,
    TagAcquiredEvent,
    TagLostEvent,
    TaskDividedEvent,
    TaskAggregatedEvent,
)


def format_timeline(events: list[ClaimEvent]) -> str:
    """Timeline verticale, une ligne par event, triée par timestamp."""
    if not events:
        return ""

    # Sort events by timestamp
    sorted_events = sorted(events, key=lambda e: e.timestamp)

    lines = []
    for event in sorted_events:
        time_str = event.timestamp.strftime("%H:%M:%S")

        if isinstance(event, Phase1FilteredEvent):
            if event.passed:
                line = f"[{time_str}] PHASE1 {event.agent_id} -> passed (fit={event.fit_score:.2f})"
            else:
                line = f"[{time_str}] PHASE1 {event.agent_id} -> filtered"
            lines.append(line)

        elif isinstance(event, Phase2ClaimedEvent):
            justification = event.justification
            if len(justification) > 50:
                justification_display = justification[:50] + "..."
            else:
                justification_display = justification
            line = f"[{time_str}] PHASE2 {event.agent_id} -> {event.decision} ({justification_display})"
            lines.append(line)

        elif isinstance(event, DispatchedEvent):
            line = f"[{time_str}] DISPATCH -> {event.agent_id} ({event.reason})"
            lines.append(line)

        elif isinstance(event, ExecutedEvent):
            output_summary = event.output_summary
            if len(output_summary) > 60:
                output_display = output_summary[:60] + "..."
            else:
                output_display = output_summary
            line = f"[{time_str}] EXECUTED -> {event.agent_id} ({output_display})"
            lines.append(line)

        elif isinstance(event, UnassignedEvent):
            line = f"[{time_str}] UNASSIGNED -> {event.reason}"
            lines.append(line)

        elif isinstance(event, QAEvaluatedEvent):
            verdict = "PASS" if event.success else "FAIL"
            line = f"[{time_str}] QA {event.agent_id} -> {verdict} (score={event.score:.2f})"
            lines.append(line)

        elif isinstance(event, EloUpdatedEvent):
            deltas_str = ", ".join(
                f"{tag}: {'+' if d > 0 else ''}{d}"
                for tag, d in event.deltas.items()
            )
            line = f"[{time_str}] ELO {event.agent_id} -> {deltas_str}"
            lines.append(line)

        elif isinstance(event, TagAcquiredEvent):
            line = f"[{time_str}] ACQUIRED {event.agent_id} -> {event.tag}: {event.initial_elo} (new tag)"
            lines.append(line)

        elif isinstance(event, TagLostEvent):
            line = f"[{time_str}] LOST {event.agent_id} -> {event.tag}: {event.last_elo} (tag removed)"
            lines.append(line)

        elif isinstance(event, TaskDividedEvent):
            line = f"[{time_str}] DIVIDED -> {len(event.sub_tasks)} sub-tasks"
            lines.append(line)

        elif isinstance(event, TaskAggregatedEvent):
            summary = event.output_summary
            summary_display = summary[:60] + "..." if len(summary) > 60 else summary
            line = f"[{time_str}] AGGREGATED <- {len(event.sub_task_ids)} sub-tasks ({summary_display})"
            lines.append(line)

    return "\n".join(lines)


def print_timeline(events: list[ClaimEvent]) -> None:
    """Convenience wrapper that prints format_timeline to stdout."""
    print(format_timeline(events))
