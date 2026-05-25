import time
import uuid

from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field, field_validator

from aaosa.schemas.claim import Claim
from aaosa.schemas.output import Output, LLMMetadata
from aaosa.schemas.task import Task


class Agent(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

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

    def claim(self, task: Task, client: OpenAI) -> Claim:
        raise NotImplementedError

    def execute(self, task: Task, client: OpenAI) -> Output:
        start = time.monotonic()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": task.description},
            ],
        )
        latency_ms = (time.monotonic() - start) * 1000
        return Output(
            task_id=task.id,
            agent_id=self.id,
            content=response.choices[0].message.content or "",
            llm_metadata=LLMMetadata(
                model_name=response.model,
                tokens_in=response.usage.prompt_tokens,
                tokens_out=response.usage.completion_tokens,
                latency_ms=latency_ms,
            ),
        )
