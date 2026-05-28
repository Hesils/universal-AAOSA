import json
from typing import Callable

from pydantic import BaseModel, ConfigDict

from aaosa.schemas.output import Output
from aaosa.schemas.task import Task


class CriterionOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    passed: bool
    score: float       # 0.0-1.0
    detail: str


Criterion = Callable[[Task, Output, dict], CriterionOutcome]

CRITERIA_REGISTRY: dict[str, Criterion] = {}


def register_criterion(name: str) -> Callable[[Criterion], Criterion]:
    def deco(fn: Criterion) -> Criterion:
        CRITERIA_REGISTRY[name] = fn
        return fn
    return deco


def get_criterion(name: str) -> Criterion:
    if name not in CRITERIA_REGISTRY:
        raise ValueError(f"unknown criterion: {name!r}")
    return CRITERIA_REGISTRY[name]


@register_criterion("non_empty")
def non_empty(task: Task, output: Output, params: dict) -> CriterionOutcome:
    passed = len(output.content.strip()) > 0
    return CriterionOutcome(
        name="non_empty", passed=passed, score=1.0 if passed else 0.0,
        detail=f"{len(output.content)} chars",
    )


@register_criterion("min_length")
def min_length(task: Task, output: Output, params: dict) -> CriterionOutcome:
    threshold = params.get("min_chars", 50)
    n = len(output.content)
    score = min(1.0, n / threshold) if threshold > 0 else 1.0
    return CriterionOutcome(
        name="min_length", passed=n >= threshold, score=score,
        detail=f"{n}/{threshold} chars",
    )


@register_criterion("references_tags")
def references_tags(task: Task, output: Output, params: dict) -> CriterionOutcome:
    tags = params.get("tags") or list(task.required_tags)
    content_lower = output.content.lower()
    present = [t for t in tags if t.lower() in content_lower]
    score = len(present) / len(tags) if tags else 1.0
    return CriterionOutcome(
        name="references_tags", passed=len(present) == len(tags), score=score,
        detail=f"{len(present)}/{len(tags)} tags referenced",
    )


@register_criterion("keyword_presence")
def keyword_presence(task: Task, output: Output, params: dict) -> CriterionOutcome:
    keywords = params.get("keywords", [])
    if not keywords:
        return CriterionOutcome(name="keyword_presence", passed=True, score=1.0, detail="no keywords")
    content_lower = output.content.lower()
    present = [k for k in keywords if k.lower() in content_lower]
    score = len(present) / len(keywords)
    return CriterionOutcome(
        name="keyword_presence", passed=len(present) == len(keywords), score=score,
        detail=f"{len(present)}/{len(keywords)} keywords present",
    )


@register_criterion("format_check")
def format_check(task: Task, output: Output, params: dict) -> CriterionOutcome:
    kind = params.get("kind", "non_empty_lines")
    content = output.content
    if kind == "json":
        try:
            json.loads(content)
            passed = True
        except (json.JSONDecodeError, ValueError):
            passed = False
    elif kind == "code_block":
        passed = "```" in content
    else:  # non_empty_lines
        passed = any(line.strip() for line in content.splitlines())
    return CriterionOutcome(
        name="format_check", passed=passed, score=1.0 if passed else 0.0,
        detail=f"kind={kind}",
    )
