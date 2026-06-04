from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field, model_validator

from aaosa.schemas.task import Task


class SubTaskSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str
    depends_on_indices: list[int] = Field(default_factory=list)


class DivisionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_atomic: bool = False
    sub_tasks: list[SubTaskSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def atomic_xor_subtasks(self) -> "DivisionResult":
        if self.is_atomic and self.sub_tasks:
            raise ValueError("atomic division cannot have sub_tasks")
        if not self.is_atomic and not self.sub_tasks:
            raise ValueError("non-atomic division must have sub_tasks")
        return self


class TaskDivider:
    def __init__(self, system_prompt: str) -> None:
        self.system_prompt = system_prompt

    def _build_divide_prompt(self, task: Task) -> str:
        return (
            "If the task is atomic (a single capability, not usefully decomposable),\n"
            "set is_atomic=true and return no sub-tasks.\n"
            "Otherwise set is_atomic=false and decompose it into ordered sub-tasks, each\n"
            "a description plus dependencies (0-based indices into your sub_tasks list).\n"
            "Do NOT assign tags — only describe the work and its ordering.\n\n"
            f"Task: {task.description}"
        )

    def divide(self, task: Task, client: OpenAI) -> "DivisionResult":
        """LLM call → DivisionResult (structurel, sans tags). Ne construit pas de Task,
        ne résout pas les deps, n'émet aucun event — c'est le runner (build_sub_tasks)."""
        response = client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            temperature=0.0,
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": self._build_divide_prompt(task)},
            ],
            response_format=DivisionResult,
        )
        parsed = response.choices[0].message.parsed
        if parsed is None:
            raise ValueError("divider returned no parsed DivisionResult")
        return parsed
