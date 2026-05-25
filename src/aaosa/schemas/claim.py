"""Schema for agent claim decisions in the AAOSA runtime."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Claim(BaseModel):
    """Agent claim to execute a task.

    Attributes:
        agent_id: Unique identifier of the agent making the claim.
        task_id: Unique identifier of the task being claimed.
        decision: Whether the agent claims or declines the task.
        justification: Reason for the decision.
        timestamp: When the claim was made (auto-generated if omitted).
    """

    agent_id: str
    task_id: str
    decision: Literal["claim", "no_claim"]
    justification: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    model_config = ConfigDict(extra="forbid")
