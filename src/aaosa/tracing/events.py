from datetime import datetime, timezone
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from aaosa.qa.judge import JudgeBreakdown
from aaosa.qa.spec import EvaluatorSpec
from aaosa.schemas.output import LLMMetadata


class _BaseEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str
    task_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DividedSubTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    description: str
    depends_on: list[str] = Field(default_factory=list)
    required_tags: dict[str, int] = Field(default_factory=dict)


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
    output_content: str | None = None
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
    criteria_results: dict[str, bool] = Field(default_factory=dict)
    judge: JudgeBreakdown | None = None
    spec: EvaluatorSpec | None = None


class EloUpdatedEvent(_BaseEvent):
    type: Literal["elo_updated"] = "elo_updated"
    agent_id: str
    deltas: dict[str, int]


class TagAcquiredEvent(_BaseEvent):
    type: Literal["tag_acquired"] = "tag_acquired"
    agent_id: str
    tag: str
    initial_elo: int


class ToolCalledEvent(_BaseEvent):
    type: Literal["tool_called"] = "tool_called"
    agent_id: str
    tool_name: str
    arguments: dict
    result: str
    latency_ms: float


class TaskDividedEvent(_BaseEvent):
    type: Literal["task_divided"] = "task_divided"
    task_id: str                    # parent task ID
    sub_tasks: list[DividedSubTask]  # sous-tâches générées (id + description + depends_on)


class TaskAggregatedEvent(_BaseEvent):
    type: Literal["task_aggregated"] = "task_aggregated"
    task_id: str                    # parent task ID
    sub_task_ids: list[str]
    output_summary: str
    output_content: str
    llm_metadata: LLMMetadata | None = None


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
        ToolCalledEvent,
        TaskDividedEvent,
        TaskAggregatedEvent,
    ],
    Field(discriminator="type"),
]
