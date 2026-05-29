from datetime import datetime, timezone
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from aaosa.schemas.output import LLMMetadata


class _BaseEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str
    task_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Phase1FilteredEvent(_BaseEvent):
    type: Literal["phase1_filtered"] = "phase1_filtered"
    agent_id: str
    passed: bool
    fit_score: float


class Phase2ClaimedEvent(_BaseEvent):
    type: Literal["phase2_claimed"] = "phase2_claimed"
    agent_id: str
    decision: Literal["claim", "no_claim"]
    justification: str


class DispatchedEvent(_BaseEvent):
    type: Literal["dispatched"] = "dispatched"
    agent_id: str
    reason: str


class ExecutedEvent(_BaseEvent):
    type: Literal["executed"] = "executed"
    agent_id: str
    output_summary: str
    llm_metadata: LLMMetadata | None = None


class UnassignedEvent(_BaseEvent):
    type: Literal["unassigned"] = "unassigned"
    reason: str


class QAEvaluatedEvent(_BaseEvent):
    type: Literal["qa_evaluated"] = "qa_evaluated"
    agent_id: str
    success: bool
    score: float
    reason: str


class EloUpdatedEvent(_BaseEvent):
    type: Literal["elo_updated"] = "elo_updated"
    agent_id: str
    deltas: dict[str, int]


class TagAcquiredEvent(_BaseEvent):
    type: Literal["tag_acquired"] = "tag_acquired"
    agent_id: str
    tag: str
    initial_elo: int


ClaimEvent = Annotated[
    Union[
        Phase1FilteredEvent,
        Phase2ClaimedEvent,
        DispatchedEvent,
        ExecutedEvent,
        UnassignedEvent,
        QAEvaluatedEvent,
        EloUpdatedEvent,
        TagAcquiredEvent,
    ],
    Field(discriminator="type"),
]
