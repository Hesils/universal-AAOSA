import uuid
from datetime import datetime, timezone
from pydantic import BaseModel, ConfigDict, Field, field_validator

from aaosa.schemas.output import Output  # output.py n'importe pas task.py — pas de circularité


class Task(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    description: str
    required_tags: dict[str, int]
    acquirable_tags: dict[str, int] = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # V3 (A3) — subdivision de tâches : tous optionnels, rétrocompat stricte
    parent_task_id: str | None = None
    order_index: int | None = None
    depends_on: list[str] = Field(default_factory=list)         # IDs de tâches sœurs
    required_outputs: list[Output] = Field(default_factory=list)  # rempli par run_chain

    @field_validator("required_tags")
    @classmethod
    def required_tags_not_empty(cls, v):
        if not v:
            raise ValueError("required_tags cannot be empty")
        return v
