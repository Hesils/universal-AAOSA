from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from aaosa.claiming.dispatch import DispatchResult
from aaosa.core.agent import Agent
from aaosa.runtime.runner import run_chain, run_task
from aaosa.schemas.claim import Claim
from aaosa.schemas.output import LLMMetadata, Output
from aaosa.schemas.task import Task


def make_agent(name="AgentA", elo=80) -> Agent:
    return Agent(
        name=name,
        tags_with_elo={"python": elo, "backend": elo},
        system_prompt=f"You are {name}.",
    )


def make_task(description="t", required_tags=None, depends_on=None) -> Task:
    return Task(
        description=description,
        required_tags=required_tags or {"python": 60},
        depends_on=depends_on or [],
    )


def _claim_for(agent):
    def _claim(task, client, decision="claim"):
        return Claim(agent_id=agent.id, task_id=task.id, decision="claim", justification="ok")
    return _claim


def _recording_execute(recorded):
    def fake_execute(self, task, client, tracer=None):
        recorded[task.id] = list(task.required_outputs)
        return Output(
            task_id=task.id,
            agent_id=self.id,
            content=f"out-{task.description}",
            llm_metadata=LLMMetadata(model_name="m", tokens_in=1, tokens_out=1, latency_ms=1.0),
        )
    return fake_execute


class TestRunChain:
    def test_no_deps(self):
        a = make_agent()
        t1, t2, t3 = make_task("A"), make_task("B"), make_task("C")
        recorded = {}
        with patch.object(Agent, "claim", _claim_for(a)):
            with patch.object(Agent, "execute", _recording_execute(recorded)):
                results = run_chain([t1, t2, t3], [a], MagicMock())
        assert [r.task_id for r in results] == [t1.id, t2.id, t3.id]
        assert all(isinstance(r, Output) for r in results)

    def test_linear_deps(self):
        a = make_agent()
        t1 = make_task("A")
        t2 = make_task("B", depends_on=[t1.id])
        t3 = make_task("C", depends_on=[t2.id])
        recorded = {}
        with patch.object(Agent, "claim", _claim_for(a)):
            with patch.object(Agent, "execute", _recording_execute(recorded)):
                run_chain([t3, t2, t1], [a], MagicMock())  # unordered input
        assert [o.task_id for o in recorded[t2.id]] == [t1.id]
        assert [o.task_id for o in recorded[t3.id]] == [t2.id]

    def test_diamond_deps(self):
        a = make_agent()
        t_a = make_task("A")
        t_b = make_task("B", depends_on=[t_a.id])
        t_c = make_task("C", depends_on=[t_a.id])
        t_d = make_task("D", depends_on=[t_b.id, t_c.id])
        recorded = {}
        with patch.object(Agent, "claim", _claim_for(a)):
            with patch.object(Agent, "execute", _recording_execute(recorded)):
                run_chain([t_a, t_b, t_c, t_d], [a], MagicMock())
        assert {o.task_id for o in recorded[t_d.id]} == {t_b.id, t_c.id}

    def test_zero_deps_receives_no_outputs(self):
        a = make_agent()
        t1 = make_task("A")
        recorded = {}
        with patch.object(Agent, "claim", _claim_for(a)):
            with patch.object(Agent, "execute", _recording_execute(recorded)):
                run_chain([t1], [a], MagicMock())
        assert recorded[t1.id] == []

    def test_execution_error_is_contained(self):
        # Une sous-tâche dont l'exécution lève (ex: MAX_TOOL_ROUNDS) ne doit pas
        # tuer la chaîne : elle est marquée execution_failed, les autres continuent.
        a = make_agent()
        t1 = make_task("A")                       # lèvera
        t2 = make_task("B")                       # indépendante -> réussit
        t3 = make_task("C", depends_on=[t1.id])   # dépend de la tâche en échec

        def exploding_execute(self, task, client, tracer=None):
            if task.description == "A":
                raise RuntimeError("max tool rounds exceeded")
            return Output(
                task_id=task.id, agent_id=self.id, content="ok",
                llm_metadata=LLMMetadata(model_name="m", tokens_in=1, tokens_out=1, latency_ms=1.0),
            )

        with patch.object(Agent, "claim", _claim_for(a)):
            with patch.object(Agent, "execute", exploding_execute):
                results = run_chain([t1, t2, t3], [a], MagicMock())

        assert isinstance(results[0], DispatchResult) and results[0].status == "execution_failed"
        assert isinstance(results[1], Output) and results[1].task_id == t2.id
        assert isinstance(results[2], DispatchResult) and results[2].status == "dependency_failed"

    def test_dependency_failed_skips(self):
        a = make_agent()
        t1 = make_task("A")
        # B requires a tag the agent lacks -> unassigned -> no output
        t_b = Task(description="B", required_tags={"rust": 99})
        t_c = make_task("C", depends_on=[t_b.id])
        recorded = {}
        with patch.object(Agent, "claim", _claim_for(a)):
            with patch.object(Agent, "execute", _recording_execute(recorded)):
                results = run_chain([t1, t_b, t_c], [a], MagicMock())
        by_id = {getattr(r, "task_id", None): r for r in results}
        # C must be dependency_failed and never executed
        c_result = next(r for r in results if isinstance(r, DispatchResult) and r.status == "dependency_failed")
        assert t_c.id not in recorded
        assert c_result.status == "dependency_failed"

    def test_cycle_raises(self):
        a = make_agent()
        t1 = make_task("A")
        t2 = make_task("B")
        t1.depends_on = [t2.id]
        t2.depends_on = [t1.id]
        with pytest.raises(ValueError, match="cycle"):
            run_chain([t1, t2], [a], MagicMock())

    def test_unknown_dependency_raises(self):
        a = make_agent()
        t1 = make_task("A", depends_on=["does-not-exist"])
        with pytest.raises(ValueError, match="unknown dependency"):
            run_chain([t1], [a], MagicMock())

    def test_run_task_unchanged_with_depends_on(self):
        # run_task alone on a Task carrying depends_on behaves like V2 (ignores depends_on)
        a = make_agent()
        task = make_task("A", depends_on=["sibling"])
        output = Output(
            task_id=task.id, agent_id=a.id, content="done",
            llm_metadata=LLMMetadata(model_name="m", tokens_in=1, tokens_out=1, latency_ms=1.0),
        )
        with patch.object(Agent, "claim", return_value=Claim(agent_id=a.id, task_id=task.id, decision="claim", justification="ok")):
            with patch.object(Agent, "execute", return_value=output):
                result = run_task(task, [a], MagicMock())
        assert isinstance(result, Output)
        assert result.task_id == task.id


class TestExecuteRequiredOutputs:
    def _fake_client(self, capture):
        def create(**kwargs):
            capture["messages"] = kwargs["messages"]
            return SimpleNamespace(
                model="gpt-4o-mini",
                choices=[SimpleNamespace(message=SimpleNamespace(content="answer"))],
                usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
            )
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    def test_execute_includes_required_outputs(self):
        a = make_agent()
        dep = Output(
            task_id="dep-1", agent_id="x", content="DEP_CONTENT_MARKER",
            llm_metadata=LLMMetadata(model_name="m", tokens_in=1, tokens_out=1, latency_ms=1.0),
        )
        task = Task(description="use the dep", required_tags={"python": 60}, required_outputs=[dep])
        capture = {}
        a.execute(task, self._fake_client(capture))
        user_msg = capture["messages"][-1]["content"]
        assert "DEP_CONTENT_MARKER" in user_msg

    def test_execute_no_required_outputs_omits_section(self):
        a = make_agent()
        task = Task(description="standalone", required_tags={"python": 60})
        capture = {}
        a.execute(task, self._fake_client(capture))
        user_msg = capture["messages"][-1]["content"]
        assert "Required context from previous steps" not in user_msg
