from types import SimpleNamespace
from unittest.mock import patch

import pytest

from aaosa.claiming.dispatch import DispatchResult
from aaosa.core.agent import Agent
from aaosa.runtime.context import RunContext
from aaosa.runtime.divider import DivisionResult, SubTaskSpec
from aaosa.runtime.runner import build_sub_tasks, run_recovery, run_with_recovery
from aaosa.runtime.tagger import EmptyTaggingError
from aaosa.schemas.elo import DEFAULT_REQUIRED_ELO
from aaosa.schemas.output import LLMMetadata, Output
from aaosa.schemas.task import Task
from aaosa.tracing.events import RosterGapEvent, TaskDividedEvent
from aaosa.tracing.tracer import Tracer


def make_agent(name="A", **tags) -> Agent:
    return Agent(name=name, tags_with_elo=tags or {"python": 80}, system_prompt="x")


def make_output(task_id="t", content="c") -> Output:
    return Output(
        task_id=task_id, agent_id="x", content=content,
        llm_metadata=LLMMetadata(model_name="m", tokens_in=1, tokens_out=1, latency_ms=1.0),
    )


class _FakeTagger:
    def __init__(self, mapping=None, default=("python",)):
        self.mapping = mapping or {}
        self.default = set(default)

    def tag(self, description, agents, client):
        return set(self.mapping.get(description, self.default))


class _StaticDivider:
    def __init__(self, division):
        self.division = division

    def divide(self, task, client):
        return self.division


class _RecordingAggregator:
    def aggregate(self, parent_task, sub_outputs, client, tracer=None):
        return make_output(parent_task.id, "agg")


class _ExplodingAggregator:
    def aggregate(self, parent_task, sub_outputs, client, tracer=None):
        raise RuntimeError("boom")


def _ctx(divider, tagger=None, aggregator=None, tracer=None, agents=None):
    return RunContext(
        agents=agents or [make_agent()],
        client=object(),
        divider=divider,
        aggregator=aggregator or _RecordingAggregator(),
        tagger=tagger or _FakeTagger(),
        tracer=tracer,
    )


def _two_subtask_division():
    return DivisionResult(sub_tasks=[
        SubTaskSpec(description="s1"),
        SubTaskSpec(description="s2", depends_on_indices=[0]),
    ])


class TestRunWithRecovery:
    def test_flat_success_no_division(self):
        ctx = _ctx(_StaticDivider(_two_subtask_division()))
        task = Task(description="t", required_tags={"python": 30})
        with patch("aaosa.runtime.runner.run_task", return_value=make_output("t")) as rt:
            result = run_with_recovery(task, ctx)
        assert isinstance(result, Output)
        rt.assert_called_once()

    def test_unassigned_triggers_division_then_aggregates(self):
        ctx = _ctx(_StaticDivider(_two_subtask_division()))
        task = Task(description="t", required_tags={"python": 30})
        unassigned = DispatchResult(status="unassigned", agent_id=None, reason="no claim")
        with patch("aaosa.runtime.runner.run_task", return_value=unassigned):
            with patch("aaosa.runtime.runner.run_chain", return_value=[make_output("s1"), make_output("s2")]):
                result = run_with_recovery(task, ctx)
        assert isinstance(result, Output)
        assert result.content == "agg"

    def test_atomic_verdict_is_dead_end(self):
        ctx = _ctx(_StaticDivider(DivisionResult(is_atomic=True, sub_tasks=[])))
        task = Task(description="t", required_tags={"python": 30})
        unassigned = DispatchResult(status="unassigned", agent_id=None, reason="no claim")
        with patch("aaosa.runtime.runner.run_task", return_value=unassigned):
            with patch("aaosa.runtime.runner.run_chain") as rc:
                result = run_with_recovery(task, ctx)
        assert isinstance(result, DispatchResult)
        assert result.status == "unassigned"
        rc.assert_not_called()

    def test_depth_cap_stops_recursion(self):
        ctx = _ctx(_StaticDivider(_two_subtask_division()))
        task = Task(description="t", required_tags={"python": 30})
        unassigned = DispatchResult(status="unassigned", agent_id=None, reason="no claim")
        with patch("aaosa.runtime.runner.run_task", return_value=unassigned):
            with patch("aaosa.runtime.runner.run_chain") as rc:
                result = run_with_recovery(task, ctx, depth=3)
        assert result.status == "unassigned"
        rc.assert_not_called()

    def test_roster_gap_short_circuits_and_emits_event(self):
        tracer = Tracer(session_id="s")
        ctx = _ctx(_StaticDivider(_two_subtask_division()), tracer=tracer,
                   agents=[make_agent(python=80)])
        task = Task(description="t", required_tags={"python": 30, "quantum": 30})
        with patch("aaosa.runtime.runner.run_task") as rt:
            result = run_with_recovery(task, ctx)
        assert result.status == "roster_gap"
        rt.assert_not_called()
        assert any(isinstance(e, RosterGapEvent) and e.missing_tags == ["quantum"] for e in tracer.events)

    def test_no_successful_subtasks_returns_unassigned(self):
        ctx = _ctx(_StaticDivider(_two_subtask_division()))
        task = Task(description="t", required_tags={"python": 30})
        unassigned = DispatchResult(status="unassigned", agent_id=None, reason="no claim")
        with patch("aaosa.runtime.runner.run_task", return_value=unassigned):
            with patch("aaosa.runtime.runner.run_chain", return_value=[unassigned, unassigned]):
                result = run_with_recovery(task, ctx)
        assert result.status == "unassigned"
        assert result.reason == "no sub-tasks recovered"

    def test_aggregator_exception_falls_back_to_last_output(self):
        ctx = _ctx(_StaticDivider(_two_subtask_division()), aggregator=_ExplodingAggregator())
        task = Task(description="t", required_tags={"python": 30})
        unassigned = DispatchResult(status="unassigned", agent_id=None, reason="no claim")
        with patch("aaosa.runtime.runner.run_task", return_value=unassigned):
            with patch("aaosa.runtime.runner.run_chain", return_value=[make_output("s1"), make_output("s2")]):
                result = run_with_recovery(task, ctx)
        assert result.task_id == "s2"

    def test_empty_tagging_is_clean_crash(self):
        ctx = _ctx(_StaticDivider(_two_subtask_division()), tagger=_FakeTagger(default=()))
        task = Task(description="t", required_tags={"python": 30})
        unassigned = DispatchResult(status="unassigned", agent_id=None, reason="no claim")
        with patch("aaosa.runtime.runner.run_task", return_value=unassigned):
            result = run_with_recovery(task, ctx)
        assert result.status == "execution_failed"
        assert result.reason == "tagging produced no tags"

    def test_divider_exception_returns_execution_failed(self):
        class _ExplodingDivider:
            def divide(self, task, client):
                raise RuntimeError("LLM timeout")

        ctx = _ctx(_ExplodingDivider())
        task = Task(description="t", required_tags={"python": 30})
        unassigned = DispatchResult(status="unassigned", agent_id=None, reason="no claim")
        with patch("aaosa.runtime.runner.run_task", return_value=unassigned):
            result = run_with_recovery(task, ctx)
        assert result.status == "execution_failed"
        assert "divider" in result.reason


class TestBuildSubTasks:
    def test_tags_each_subtask_with_uniform_elo_and_resolves_deps(self):
        from aaosa.schemas.elo import DEFAULT_REQUIRED_ELO
        ctx = _ctx(_StaticDivider(_two_subtask_division()),
                   tagger=_FakeTagger(mapping={"s1": ("python",), "s2": ("sql",)}))
        parent = Task(description="t", required_tags={"python": 30})
        subs = build_sub_tasks(parent, _two_subtask_division(), ctx)
        assert subs[0].required_tags == {"python": DEFAULT_REQUIRED_ELO}
        assert subs[1].required_tags == {"sql": DEFAULT_REQUIRED_ELO}
        assert subs[1].depends_on == [subs[0].id]
        assert all(s.parent_task_id == parent.id for s in subs)

    def test_emits_task_divided_event_with_real_tags(self):
        tracer = Tracer(session_id="s")
        ctx = _ctx(_StaticDivider(_two_subtask_division()),
                   tagger=_FakeTagger(mapping={"s1": ("python",), "s2": ("sql",)}), tracer=tracer)
        parent = Task(description="t", required_tags={"python": 30})
        build_sub_tasks(parent, _two_subtask_division(), ctx)
        events = [e for e in tracer.events if isinstance(e, TaskDividedEvent)]
        assert len(events) == 1
        assert events[0].sub_tasks[0].required_tags == {"python": DEFAULT_REQUIRED_ELO}

    def test_raises_empty_tagging_error_on_empty(self):
        ctx = _ctx(_StaticDivider(_two_subtask_division()), tagger=_FakeTagger(default=()))
        parent = Task(description="t", required_tags={"python": 30})
        with pytest.raises(EmptyTaggingError):
            build_sub_tasks(parent, _two_subtask_division(), ctx)


class TestRunRecovery:
    def test_pinned_tags_skip_tagger(self):
        called = {"tag": False}

        class _SpyTagger(_FakeTagger):
            def tag(self, description, agents, client):
                called["tag"] = True
                return {"python"}

        ctx = _ctx(_StaticDivider(_two_subtask_division()), tagger=_SpyTagger())
        with patch("aaosa.runtime.runner.run_task", return_value=make_output("t")):
            run_recovery("t", ctx, pinned_tags={"python": 70})
        assert called["tag"] is False

    def test_unpinned_root_is_tagged(self):
        ctx = _ctx(_StaticDivider(_two_subtask_division()), tagger=_FakeTagger(default=("python",)))
        with patch("aaosa.runtime.runner.run_task", return_value=make_output("t")) as rt:
            run_recovery("do a python thing", ctx)
        passed_task = rt.call_args.args[0]
        assert "python" in passed_task.required_tags

    def test_unpinned_root_empty_tagging_clean_crash(self):
        ctx = _ctx(_StaticDivider(_two_subtask_division()), tagger=_FakeTagger(default=()))
        result = run_recovery("t", ctx)
        assert result.status == "execution_failed"
