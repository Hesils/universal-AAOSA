from collections.abc import Sequence

from aaosa.tracing.events import (
    ClaimEvent,
    DiagnosedEvent,
    Phase1FilteredEvent,
    Phase2ClaimedEvent,
    RosterGapEvent,
    TaskAggregatedEvent,
    TaskDividedEvent,
)


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


_DIAGNOSED_ORDER = ("agent", "evaluator", "task_spec", "unattributed")


def classify_run(events: Sequence[ClaimEvent]) -> list[str]:
    """Typologies d'un run détectées depuis la trace, ordre canonique fixe.

    `simple` et `divided` sont mutuellement exclusifs ; les autres labels se
    cumulent. `aggregated` = agrégation réelle uniquement (le court-circuit
    1-sink n'émet pas de TaskAggregatedEvent, règle D2). Fonction pure sans I/O.
    """
    divided = [e for e in events if isinstance(e, TaskDividedEvent)]
    labels = ["divided" if divided else "simple"]

    sub_ids = {st.id for e in divided for st in e.sub_tasks}
    if any(e.task_id in sub_ids for e in divided):
        labels.append("recursion")

    if any(isinstance(e, RosterGapEvent) for e in events):
        labels.append("roster_gap")

    seen = {e.attribution for e in events if isinstance(e, DiagnosedEvent)}
    labels.extend(f"diagnosed:{a}" for a in _DIAGNOSED_ORDER if a in seen)

    if any(isinstance(e, TaskAggregatedEvent) for e in events):
        labels.append("aggregated")

    return labels
