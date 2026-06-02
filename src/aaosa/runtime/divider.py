"""TaskDivider — décompose une tâche en sous-tâches via LLM (A4).

Aucune découpe n'est hardcodée : le graphe d'exécution émerge de la décision
du LLM. Le TaskDivider n'est PAS un Agent (pas de claim, pas de tags_with_elo).
"""

from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field, model_validator

from aaosa.core.agent import Agent
from aaosa.schemas.task import Task
from aaosa.tracing.events import DividedSubTask, TaskDividedEvent
from aaosa.tracing.tracer import Tracer


class TagSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tag: str
    elo: int


class SubTaskSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str
    required_tags: list[TagSpec]  # list car dict interdit par OpenAI structured output
    depends_on_indices: list[int] = Field(default_factory=list)  # indices 0-based dans sub_tasks


class DivisionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sub_tasks: list[SubTaskSpec]

    @model_validator(mode="after")
    def at_least_one(self) -> "DivisionResult":
        if not self.sub_tasks:
            raise ValueError("sub_tasks cannot be empty")
        return self


class TaskDivider:
    def __init__(self, system_prompt: str) -> None:
        self.system_prompt = system_prompt

    def _build_divide_prompt(self, task: Task, agents: list[Agent]) -> str:
        tags = sorted({t for a in agents for t in a.tags_with_elo})
        return (
            "Available agent tags (reference vocabulary — not exhaustive):\n"
            f"  {', '.join(tags)}\n\n"
            "These tags exist in the current agent roster. Use them when appropriate.\n"
            "You may use other tags if a sub-task genuinely requires a capability\n"
            "not covered above — but prefer the existing vocabulary when it fits.\n"
            "If you use an unknown tag, no agent may be able to claim that sub-task.\n\n"
            "Decompose the following task into ordered sub-tasks.\n"
            "Every sub-task MUST list at least one required tag (prefer the vocabulary above).\n"
            "Express dependencies between sub-tasks as 0-based indices into your sub_tasks list.\n\n"
            f"Task: {task.description}"
        )

    def divide(
        self,
        task: Task,
        agents: list[Agent],
        client: OpenAI,
        tracer: Tracer | None = None,
    ) -> list[Task]:
        """LLM call → list[Task] avec parent_task_id, order_index, depends_on résolus."""
        prompt = self._build_divide_prompt(task, agents)
        response = client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            temperature=0.0,
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": prompt},
            ],
            response_format=DivisionResult,
        )
        parsed = response.choices[0].message.parsed
        if parsed is None:
            raise ValueError("divider returned no parsed DivisionResult")

        sub_tasks = [
            Task(
                description=spec.description,
                # Garde : le LLM peut omettre les tags (ex: sous-tâche de synthèse).
                # Task interdit required_tags vide → on hérite des tags du parent.
                required_tags={ts.tag: ts.elo for ts in spec.required_tags} or dict(task.required_tags),
                parent_task_id=task.id,
                order_index=i,
            )
            for i, spec in enumerate(parsed.sub_tasks)
        ]
        # Résolution indice → ID réel (le LLM ne connaît pas les UUID à l'avance)
        for i, spec in enumerate(parsed.sub_tasks):
            sub_tasks[i].depends_on = [sub_tasks[j].id for j in spec.depends_on_indices]

        if tracer is not None:
            tracer.emit(TaskDividedEvent(
                session_id=tracer.session_id,
                task_id=task.id,
                sub_tasks=[
                    DividedSubTask(id=st.id, description=st.description, depends_on=list(st.depends_on))
                    for st in sub_tasks
                ],
            ))
        return sub_tasks
