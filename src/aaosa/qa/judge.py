from typing import Literal

from openai import OpenAI
from pydantic import BaseModel, ConfigDict

from aaosa.qa.spec import JudgeSpec
from aaosa.schemas.output import Output
from aaosa.schemas.task import Task


class DimensionScore(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    score: float  # 0.0-1.0


class JudgeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dimension_scores: list[DimensionScore]
    overall: float
    reason: str


class JudgeBreakdown(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["rubric", "reference_based"]
    overall: float
    dimension_scores: list[DimensionScore]
    reason: str


_SYSTEM = (
    "You are a strict QA judge. Score the agent output against the task on each "
    "rubric dimension from 0.0 to 1.0, then give an overall score (0.0-1.0) and a short reason. "
    "Be conservative: reward only what is actually present in the output."
)


def _build_user_message(
    task: Task, output: Output, spec: JudgeSpec, reference: str | None
) -> str:
    parts = [
        f"# Task\n{task.description}",
        f"# Required tags\n{', '.join(task.required_tags)}",
        f"# Rubric dimensions\n{', '.join(spec.rubric)}",
        f"# Agent output\n{output.content}",
    ]
    if spec.instructions:
        parts.append(f"# Extra instructions\n{spec.instructions}")
    if spec.mode == "reference_based" and reference is not None:
        parts.append(f"# Reference (ideal answer)\n{reference}")
    return "\n\n".join(parts)


def run_judge(
    task: Task,
    output: Output,
    spec: JudgeSpec,
    client: OpenAI,
    reference: str | None = None,
) -> JudgeResult:
    user_message = _build_user_message(task, output, spec, reference)
    response = client.beta.chat.completions.parse(
        model=spec.model,
        temperature=spec.temperature,
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": user_message},
        ],
        response_format=JudgeResult,
    )
    parsed = response.choices[0].message.parsed
    if parsed is None:
        raise ValueError("judge returned no parsed result")
    return parsed
