import json
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
        from aaosa.claiming.prompts import prompt_template  # local import to avoid circular dependency

        user_message = prompt_template(self, task)

        # Try OpenAI structured output (SDK 2.x)
        try:
            response = client.beta.chat.completions.parse(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": user_message},
                ],
                response_format=Claim,
            )
            parsed = response.choices[0].message.parsed
            if parsed is not None:
                return Claim(
                    agent_id=self.id,
                    task_id=task.id,
                    decision=parsed.decision,
                    justification=parsed.justification,
                )
        except Exception:
            pass  # structured output unavailable or failed — fall through to JSON fallback

        # Fallback: raw completion + JSON parse
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_message},
            ],
        )
        raw = response.choices[0].message.content or ""
        try:
            data = json.loads(raw)
            return Claim(
                agent_id=self.id,
                task_id=task.id,
                decision=data["decision"],
                justification=data["justification"],
            )
        except (json.JSONDecodeError, KeyError) as e:
            raise ValueError(f"Failed to parse claim from LLM response: {e!r}. Raw: {raw!r}") from e

    def execute(self, task: Task, client: OpenAI) -> Output:
        context = task.metadata.get("context", "")
        deps = ""
        if task.required_outputs:
            deps = "\n\n# Required context from previous steps\n" + "\n---\n".join(
                f"[{o.task_id}]: {o.content}" for o in task.required_outputs
            )
        user_content = f"{task.description}{deps}"
        if context:
            user_content = f"{user_content}\n\n{context}"
        user_content = user_content.strip()
        start = time.monotonic()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_content},
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
