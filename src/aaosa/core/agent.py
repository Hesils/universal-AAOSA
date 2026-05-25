import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from aaosa.schemas.claim import Claim
from aaosa.schemas.output import Output
from aaosa.schemas.task import Task


class Agent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    tags_with_elo: dict[str, int]
    system_prompt: str

    @field_validator("tags_with_elo")
    @classmethod
    def tags_with_elo_not_empty(cls, v):
        if not v:
            raise ValueError("tags_with_elo cannot be empty")
        return v

    def claim(self, task: Task, client: Any) -> Claim:
        raise NotImplementedError

    def execute(self, task: Task, client: Any) -> Output:
        raise NotImplementedError
