from aaosa.tracing.events import ClaimEvent, Phase1FilteredEvent, Phase2ClaimedEvent


def _build_indexes(
    events: list[ClaimEvent],
) -> tuple[dict[tuple[str, str], Phase1FilteredEvent], dict[tuple[str, str], Phase2ClaimedEvent]]:
    phase1 = {(e.task_id, e.agent_id): e for e in events if isinstance(e, Phase1FilteredEvent)}
    phase2 = {(e.task_id, e.agent_id): e for e in events if isinstance(e, Phase2ClaimedEvent)}
    return phase1, phase2


def detect_overclaims(events: list[ClaimEvent]) -> list[dict]:
    """
    Over-claim: agent decided 'claim' in Phase2 but had fit_score < 1.0 in Phase1.
    fit_score < 1.0 means the agent is below the weighted ELO threshold when acquirable
    tags are counted. Note: passes_filter uses only required_tags, so a Phase1 pass does
    NOT guarantee fit_score >= 1.0. Threshold is exclusive: 1.0 is NOT an overclaim.

    Returns list of dicts with keys: agent_id, task_id, fit_score, justification.
    """
    phase1, phase2 = _build_indexes(events)
    overclaims = []
    for (task_id, agent_id), p2 in phase2.items():
        if p2.decision == "claim":
            p1 = phase1.get((task_id, agent_id))
            if p1 is not None and p1.fit_score < 1.0:
                overclaims.append({
                    "agent_id": agent_id,
                    "task_id": task_id,
                    "fit_score": p1.fit_score,
                    "justification": p2.justification,
                })
    return overclaims


def detect_underclaims(events: list[ClaimEvent]) -> list[dict]:
    """
    Under-claim: agent passed Phase1 (passed=True) but decided 'no_claim' in Phase2.
    Normal individually, but a signal if systemic.

    Returns list of dicts with keys: agent_id, task_id, fit_score, justification.
    """
    phase1, phase2 = _build_indexes(events)
    underclaims = []
    for (task_id, agent_id), p1 in phase1.items():
        if p1.passed:
            p2 = phase2.get((task_id, agent_id))
            if p2 is not None and p2.decision == "no_claim":
                underclaims.append({
                    "agent_id": agent_id,
                    "task_id": task_id,
                    "fit_score": p1.fit_score,
                    "justification": p2.justification,
                })
    return underclaims
