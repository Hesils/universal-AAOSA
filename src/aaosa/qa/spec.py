from typing import Literal

from pydantic import BaseModel, ConfigDict


class CriterionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    params: dict = {}
    weight: float = 1.0
    gate: bool = False
    rationale: str = ""


class JudgeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["rubric", "reference_based"] = "rubric"
    model: str = "gpt-4o-mini"
    rubric: list[str]
    weight: float = 0.3
    temperature: float = 0.0
    instructions: str = ""


class EvaluatorSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    criteria: list[CriterionSpec]
    judge: JudgeSpec | None = None
    success_threshold: float = 0.7
