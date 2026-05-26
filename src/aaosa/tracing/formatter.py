from aaosa.tracing.events import (
    ClaimEvent,
    Phase1FilteredEvent,
    Phase2ClaimedEvent,
    DispatchedEvent,
    ExecutedEvent,
    UnassignedEvent,
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

    return "\n".join(lines)


def print_timeline(events: list[ClaimEvent]) -> None:
    """Convenience wrapper that prints format_timeline to stdout."""
    print(format_timeline(events))
