from pathlib import Path

import pytest

from aaosa.qa.spec import CriterionSpec, EvaluatorSpec
from aaosa.qa.protocol import QAFailure, QAResult
from aaosa.qa.test_set import (
    TestCase,
    TestSet,
    save_test_set,
    load_test_set,
    failure_to_test_case,
    active_cases,
)
from aaosa.schemas.output import Output, LLMMetadata
from aaosa.schemas.task import Task


def make_task() -> Task:
    return Task(description="do x", required_tags={"python": 80})


def make_spec() -> EvaluatorSpec:
    return EvaluatorSpec(criteria=[CriterionSpec(name="non_empty", gate=True)])


def make_output() -> Output:
    return Output(
        task_id="t1", agent_id="a1", content="bad",
        llm_metadata=LLMMetadata(model_name="m", tokens_in=1, tokens_out=1, latency_ms=1.0),
    )


def make_failure(task: Task) -> QAFailure:
    out = make_output()
    out = out.model_copy(update={"task_id": task.id})
    return QAFailure(
        task_id=task.id, agent_id="a1", output=out,
        qa_result=QAResult(task_id=task.id, agent_id="a1", success=False,
                           score=0.2, reason="too short", criteria_results={"non_empty": True}),
    )


class TestTestCase:
    def test_defaults(self):
        tc = TestCase(task=make_task(), evaluator_spec=make_spec(), origin="curated", role="regression_guard")
        assert tc.reference is None
        assert tc.wrong_output is None
        assert tc.attribution == "unattributed"

    def test_full(self):
        tc = TestCase(
            task=make_task(), evaluator_spec=make_spec(), reference="ideal",
            origin="runtime_failure", wrong_output=make_output(),
            role="fix_target", attribution="agent",
        )
        assert tc.reference == "ideal"
        assert tc.role == "fix_target"

    def test_invalid_origin(self):
        with pytest.raises(Exception):
            TestCase(task=make_task(), evaluator_spec=make_spec(), origin="bogus", role="fix_target")

    def test_extra_forbidden(self):
        with pytest.raises(Exception):
            TestCase(task=make_task(), evaluator_spec=make_spec(), origin="curated",
                     role="fix_target", bogus=1)


class TestTestSetPersistence:
    def test_save_creates_latest(self, tmp_path):
        ts = TestSet(cases=[TestCase(task=make_task(), evaluator_spec=make_spec(),
                                     origin="curated", role="regression_guard")])
        save_test_set(ts, tmp_path)
        assert (tmp_path / "latest.json").exists()

    def test_save_returns_timestamped_path(self, tmp_path):
        ts = TestSet(cases=[])
        path = save_test_set(ts, tmp_path)
        assert isinstance(path, Path)
        assert path.name != "latest.json"
        assert path.exists()

    def test_roundtrip(self, tmp_path):
        ts = TestSet(cases=[
            TestCase(task=make_task(), evaluator_spec=make_spec(), reference="r",
                     origin="runtime_failure", wrong_output=make_output(),
                     role="fix_target", attribution="agent"),
        ])
        save_test_set(ts, tmp_path)
        loaded = load_test_set(tmp_path / "latest.json")
        assert loaded == ts

    def test_load_nonexistent_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_test_set(tmp_path / "nope.json")


class TestFailureToTestCase:
    def test_born_as_fix_target_unattributed(self):
        task = make_task()
        tc = failure_to_test_case(make_failure(task), task, make_spec())
        assert tc.origin == "runtime_failure"
        assert tc.role == "fix_target"
        assert tc.attribution == "unattributed"
        assert tc.reference is None

    def test_preserves_wrong_output(self):
        task = make_task()
        failure = make_failure(task)
        tc = failure_to_test_case(failure, task, make_spec())
        assert tc.wrong_output == failure.output


class TestActiveCases:
    def _case(self, role, attribution):
        return TestCase(task=make_task(), evaluator_spec=make_spec(),
                        origin="curated", role=role, attribution=attribution)

    def test_includes_regression_guards(self):
        ts = TestSet(cases=[self._case("regression_guard", "unattributed")])
        assert len(active_cases(ts)) == 1

    def test_includes_fix_target_attributed_agent(self):
        ts = TestSet(cases=[self._case("fix_target", "agent")])
        assert len(active_cases(ts)) == 1

    def test_excludes_fix_target_unattributed(self):
        ts = TestSet(cases=[self._case("fix_target", "unattributed")])
        assert active_cases(ts) == []

    def test_excludes_task_spec_quarantine(self):
        ts = TestSet(cases=[self._case("fix_target", "task_spec")])
        assert active_cases(ts) == []

    def test_excludes_evaluator_attributed_fix_target(self):
        ts = TestSet(cases=[self._case("fix_target", "evaluator")])
        assert active_cases(ts) == []
