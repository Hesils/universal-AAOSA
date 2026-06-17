import json
import time
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

from aaosa.core.tool import MAX_TOOL_ROUNDS, ToolDef
from aaosa.runtime.providers import LLMProvider
from aaosa.schemas.claim import Claim
from aaosa.schemas.output import Output, LLMMetadata
from aaosa.schemas.task import Task
from aaosa.tracing.events import ToolCalledEvent
from aaosa.tracing.tracer import Tracer


class Agent(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    tags_with_elo: dict[str, int]
    system_prompt: str
    tools: list[ToolDef] = Field(default_factory=list)    # A5
    provider: str | None = None   # d6i — None = provider par défaut du run
    model: str | None = None      # d6i — None = modèle par défaut du provider

    @field_validator("tags_with_elo")
    @classmethod
    def tags_with_elo_not_empty(cls, v):
        if not v:
            raise ValueError("tags_with_elo cannot be empty")
        return v

    def claim(self, task: Task, provider: LLMProvider) -> Claim:
        from aaosa.claiming.prompts import prompt_template  # éviter l'import circulaire

        user_message = prompt_template(self, task)
        parsed = provider.parse(
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_message},
            ],
            schema=Claim,
            model=self.model,
        )
        if parsed is None:
            raise ValueError("Failed to parse claim from LLM response")
        return Claim(
            agent_id=self.id,
            task_id=task.id,
            decision=parsed.decision,
            justification=parsed.justification,
        )

    def _build_user_content(self, task: Task) -> str:
        context = task.context if task.context is not None else task.metadata.get("context", "")
        deps = ""
        if task.required_outputs:
            deps = "\n\n# Required context from previous steps\n" + "\n---\n".join(
                f"[{o.task_id}]: {o.content}" for o in task.required_outputs
            )
        user_content = f"{task.description}{deps}"
        if context:
            user_content = f"{user_content}\n\n{context}"
        return user_content.strip()

    def execute(self, task: Task, provider: LLMProvider, tracer: Tracer | None = None) -> Output:
        user_content = self._build_user_content(task)
        start = time.monotonic()

        if not self.tools:
            # Chemin V1/V2 — single call
            response = provider.complete(
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": user_content},
                ],
                model=self.model,
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

        # Chemin A5 — boucle tool-use
        tool_map = {t.name: t for t in self.tools}
        openai_tools = [t.to_openai() for t in self.tools]
        messages: list = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_content},
        ]
        total_tokens_in = 0
        total_tokens_out = 0
        tool_calls_count = 0
        content = ""

        for _ in range(MAX_TOOL_ROUNDS):
            response = provider.complete(
                messages=messages,
                model=self.model,
                tools=openai_tools,
            )
            choice = response.choices[0]
            total_tokens_in += response.usage.prompt_tokens
            total_tokens_out += response.usage.completion_tokens

            if choice.finish_reason != "tool_calls":
                # "stop", "length" et tout autre motif → terminal (contenu partiel accepté)
                content = choice.message.content or ""
                break

            messages.append(choice.message)
            for tc in choice.message.tool_calls:
                tool = tool_map[tc.function.name]
                args = json.loads(tc.function.arguments)
                t_start = time.monotonic()
                result = tool.fn(**args)
                t_ms = (time.monotonic() - t_start) * 1000
                tool_calls_count += 1
                if tracer is not None:
                    tracer.emit(ToolCalledEvent(
                        session_id=tracer.session_id,
                        task_id=task.id,
                        agent_id=self.id,
                        tool_name=tc.function.name,
                        arguments=args,
                        result=result,
                        latency_ms=t_ms,
                    ))
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })
        else:
            raise RuntimeError(f"Max tool rounds ({MAX_TOOL_ROUNDS}) exceeded for task {task.id}")

        latency_ms = (time.monotonic() - start) * 1000
        return Output(
            task_id=task.id,
            agent_id=self.id,
            content=content,
            llm_metadata=LLMMetadata(
                model_name=response.model,
                tokens_in=total_tokens_in,
                tokens_out=total_tokens_out,
                latency_ms=latency_ms,
                tool_calls_count=tool_calls_count,
            ),
        )
