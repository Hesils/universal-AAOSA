from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from aaosa.qa.protocol import QAFailure
from aaosa.qa.spec import EvaluatorSpec
from aaosa.schemas.output import Output
from aaosa.schemas.task import Task


class TestCase(BaseModel):
    __test__ = False
    model_config = ConfigDict(extra="forbid")
    task: Task
    evaluator_spec: EvaluatorSpec
    reference: str | None = None
    origin: Literal["curated", "runtime_failure"]
    wrong_output: Output | None = None
    role: Literal["fix_target", "regression_guard"]
    attribution: Literal["unattributed", "agent", "task_spec", "evaluator"] = "unattributed"


class TestSet(BaseModel):
    __test__ = False
    model_config = ConfigDict(extra="forbid")
    cases: list[TestCase]


def save_test_set(test_set: TestSet, directory: Path) -> Path:
    now = datetime.now(timezone.utc)
    json_data = test_set.model_dump_json(indent=2)
    ts_path = directory / (now.strftime("%Y-%m-%dT%H-%M-%S") + ".json")
    ts_path.write_text(json_data, encoding="utf-8")
    (directory / "latest.json").write_text(json_data, encoding="utf-8")
    return ts_path


def load_test_set(path: Path) -> TestSet:
    if not path.exists():
        raise FileNotFoundError(f"Test set not found: {path}")
    return TestSet.model_validate_json(path.read_text(encoding="utf-8"))


def failure_to_test_case(
    failure: QAFailure,
    task: Task,
    evaluator_spec: EvaluatorSpec,
) -> TestCase:
    return TestCase(
        task=task,
        evaluator_spec=evaluator_spec,
        reference=None,
        origin="runtime_failure",
        wrong_output=failure.output,
        role="fix_target",
        attribution="unattributed",
    )


def active_cases(test_set: TestSet) -> list[TestCase]:
    return [
        c for c in test_set.cases
        if c.role == "regression_guard"
        or (c.role == "fix_target" and c.attribution == "agent")
    ]
