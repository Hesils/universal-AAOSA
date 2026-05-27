from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from aaosa.schemas.output import Output
from aaosa.schemas.task import Task


class QAResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    agent_id: str
    success: bool
    score: float          # 0.0-1.0
    reason: str
    criteria_results: dict[str, bool]


@runtime_checkable
class QAEvaluator(Protocol):
    def evaluate(self, task: Task, output: Output) -> QAResult: ...


class QAFailure(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    agent_id: str
    output: Output        # output rejete (conserve pour debug + health check)
    qa_result: QAResult   # verdict QA
