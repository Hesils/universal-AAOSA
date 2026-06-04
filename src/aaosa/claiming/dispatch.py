"""Schema for dispatch results in the AAOSA claiming system."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aaosa.schemas.claim import Claim
from aaosa.core.agent import Agent
from aaosa.schemas.task import Task
from aaosa.tracing.tracer import Tracer
from aaosa.tracing.events import DispatchedEvent, UnassignedEvent


class DispatchResult(BaseModel):
    """Result of task dispatch/claiming process.

    Attributes:
        status: Whether a task was assigned or remains unassigned.
        agent_id: The agent assigned to the task, or None if unassigned.
        reason: Explanation for the dispatch decision.
        all_claims: All claims received for this task.
        fit_scores: Fit scores for each agent (agent_id -> score).
    """

    status: Literal["assigned", "unassigned", "dependency_failed", "execution_failed", "roster_gap"]
    agent_id: str | None
    reason: str
    all_claims: list[Claim] = Field(default_factory=list)
    fit_scores: dict[str, float] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def agent_id_matches_status(self) -> "DispatchResult":
        if self.status == "assigned" and self.agent_id is None:
            raise ValueError("agent_id must be set when status='assigned'")
        if self.status != "assigned" and self.agent_id is not None:
            raise ValueError(f"agent_id must be None when status={self.status!r}")
        return self


def dispatch(
    claims: list[Claim],
    task: Task,
    agents: list[Agent],
    fit_scores: dict[str, float],
    tracer: Tracer | None = None,
) -> DispatchResult:
    """Select the winning agent from a list of claims.

    Args:
        claims: All claims (both "claim" and "no_claim") for this task.
        task: The task being dispatched.
        agents: All candidate agents (used for ELO tie-breaking).
        fit_scores: Pre-computed fit scores keyed by agent_id.
        tracer: Optional tracer for emitting dispatch events.

    Returns:
        DispatchResult with status "assigned" or "unassigned".
    """
    winner_claims = [c for c in claims if c.decision == "claim"]

    # Branch 0 — No claims
    if not winner_claims:
        if tracer:
            tracer.emit(UnassignedEvent(
                session_id=tracer.session_id,
                task_id=task.id,
                reason="no agents claimed",
            ))
        return DispatchResult(
            status="unassigned",
            agent_id=None,
            reason="no agents claimed",
            all_claims=claims,
            fit_scores=fit_scores,
        )

    # Branch 1 — Single claim
    if len(winner_claims) == 1:
        winning_id = winner_claims[0].agent_id
        reason = "sole claimer"
        if tracer:
            tracer.emit(DispatchedEvent(
                session_id=tracer.session_id,
                task_id=task.id,
                agent_id=winning_id,
                reason=reason,
            ))
        return DispatchResult(
            status="assigned",
            agent_id=winning_id,
            reason=reason,
            all_claims=claims,
            fit_scores=fit_scores,
        )

    # Branch N — Multiple claims: conflict resolution
    max_score = max(fit_scores.get(c.agent_id, 0.0) for c in winner_claims)
    top = [c for c in winner_claims if fit_scores.get(c.agent_id, 0.0) == max_score]

    if len(top) == 1:
        winner = top[0]
        reason = f"best fit score ({max_score:.3f})"
    else:
        # Exact score tie — lexicographic tie-break by tag ELO (highest-priority tag first)
        sorted_tags = sorted(task.required_tags, key=lambda t: task.required_tags[t], reverse=True)
        agent_map = {a.id: a for a in agents}
        missing = [c.agent_id for c in top if c.agent_id not in agent_map]
        if missing:
            raise ValueError(f"agents list missing IDs referenced in claims: {missing}")

        winner = None
        reason = "tie (degenerate config)"
        for tag in sorted_tags:
            best_elo = -1
            best_claim = None
            tied = False
            for c in top:
                elo = agent_map[c.agent_id].tags_with_elo.get(tag, 0)
                if elo > best_elo:
                    best_elo = elo
                    best_claim = c
                    tied = False
                elif elo == best_elo:
                    tied = True
            if not tied and best_claim is not None:
                winner = best_claim
                reason = "tie-broken by tag ELO"
                break

        if winner is None:
            winner = top[0]
            reason = "tie (degenerate config)"

    winning_id = winner.agent_id
    if tracer:
        tracer.emit(DispatchedEvent(
            session_id=tracer.session_id,
            task_id=task.id,
            agent_id=winning_id,
            reason=reason,
        ))
    return DispatchResult(
        status="assigned",
        agent_id=winning_id,
        reason=reason,
        all_claims=claims,
        fit_scores=fit_scores,
    )
