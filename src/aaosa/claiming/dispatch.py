"""Schema for dispatch results in the AAOSA claiming system."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aaosa.schemas.claim import Claim


class DispatchResult(BaseModel):
    """Result of task dispatch/claiming process.

    Attributes:
        status: Whether a task was assigned or remains unassigned.
        agent_id: The agent assigned to the task, or None if unassigned.
        reason: Explanation for the dispatch decision.
        all_claims: All claims received for this task.
        fit_scores: Fit scores for each agent (agent_id -> score).
    """

    status: Literal["assigned", "unassigned"]
    agent_id: str | None
    reason: str
    all_claims: list[Claim] = Field(default_factory=list)
    fit_scores: dict[str, float] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def agent_id_matches_status(self) -> "DispatchResult":
        if self.status == "assigned" and self.agent_id is None:
            raise ValueError("agent_id must be set when status='assigned'")
        if self.status == "unassigned" and self.agent_id is not None:
            raise ValueError("agent_id must be None when status='unassigned'")
        return self
