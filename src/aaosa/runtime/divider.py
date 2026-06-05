from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field, model_validator

from aaosa.qa.diagnostic import FailureContext
from aaosa.schemas.task import Task


class SubTaskSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str
    depends_on_indices: list[int] = Field(default_factory=list)
    context: str | None = None  # D3 — contexte distillé pour CETTE sous-tâche


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

    def _build_divide_prompt(
        self,
        task: Task,
        chained_context: list[Task] | None,
        failure_context: FailureContext | None,
    ) -> str:
        inherited = ""
        if chained_context:
            ancestors = "\n".join(f"- {t.description}" for t in chained_context)
            inherited = f"\n\nContexte hérité (tâches ancêtres, racine → parent):\n{ancestors}"

        own_context = f"\n\nContexte domaine de cette tâche:\n{task.context}" if task.context else ""

        failure = ""
        if failure_context is not None:
            failure = (
                "\n\nÉchec précédent à clarifier (la tâche a été jugée ambiguë):\n"
                f"- Diagnostic: {failure_context.diagnostic_reason}\n"
                f"- Verdict QA: {failure_context.qa_result.reason}\n"
                f"- Réponse produite (à désambiguïser):\n{failure_context.failed_output.content}"
            )

        return (
            "If the task is atomic (a single capability, not usefully decomposable),\n"
            "set is_atomic=true and return no sub-tasks.\n"
            "Otherwise set is_atomic=false and decompose it into ordered sub-tasks, each\n"
            "a description plus dependencies (0-based indices into your sub_tasks list).\n"
            "Do NOT assign tags — only describe the work and its ordering.\n"
            "For each sub-task, set `context`: the distilled domain context that THIS "
            "sub-task needs (from the inherited context below), focused — not a copy of "
            "the parent. Leave context null if nothing domain-specific applies.\n\n"
            f"Task: {task.description}"
            f"{own_context}"
            f"{inherited}"
            f"{failure}"
        )

    def divide(
        self,
        task: Task,
        client: OpenAI,
        chained_context: list[Task] | None = None,
        failure_context: FailureContext | None = None,
    ) -> "DivisionResult":
        """LLM call → DivisionResult (structurel, sans tags). Ne construit pas de Task,
        ne résout pas les deps, n'émet aucun event — c'est le runner (build_sub_tasks).

        chained_context / failure_context (D3) enrichissent le prompt et orientent la
        génération du `context` par sous-tâche. Le divider reste pur : il ne sait pas
        d'où viennent ces données ni qui les consomme."""
        response = client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            temperature=0.0,
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": self._build_divide_prompt(task, chained_context, failure_context)},
            ],
            response_format=DivisionResult,
        )
        parsed = response.choices[0].message.parsed
        if parsed is None:
            raise ValueError("divider returned no parsed DivisionResult")
        return parsed
