"""Wiring du retry-on-cycle dans _divide_and_recover (runner).

Direction tranchée : sur cycle détecté dans le DivisionResult, ré-invoquer le
divider UNE fois en nommant le cycle, au lieu de laisser run_chain raise.
- 1er divide cyclique + 2e acyclique → run récupéré
- deux divides cycliques → erreur contenue (execution_failed), pas de boucle
LLM mocké de bout en bout."""

from types import SimpleNamespace
from unittest.mock import patch

import aaosa.runtime.runner as runner
from aaosa.claiming.dispatch import DispatchResult
from aaosa.core.agent import Agent
from aaosa.runtime.context import RunContext
from aaosa.runtime.divider import DivisionResult, SubTaskSpec
from aaosa.schemas.claim import Claim
from aaosa.schemas.output import LLMMetadata, Output
from aaosa.schemas.task import Task
from aaosa.tracing.events import DividerCycleEvent
from aaosa.tracing.tracer import Tracer


def make_agent(name="AgentA", elo=80) -> Agent:
    return Agent(name=name, tags_with_elo={"python": elo, "backend": elo},
                 system_prompt=f"You are {name}.")


def _claim_for(agent):
    def _claim(self, task, provider, decision="claim"):
        return Claim(agent_id=agent.id, task_id=task.id, decision="claim", justification="ok")
    return _claim


def _execute(self, task, provider, tracer=None):
    return Output(task_id=task.id, agent_id=self.id, content=f"out-{task.description}",
                  llm_metadata=LLMMetadata(model_name="m", tokens_in=1, tokens_out=1, latency_ms=1.0))


class _ScriptedDivider:
    """divide() renvoie successivement les DivisionResult de `script`, en
    enregistrant les cycle_context reçus."""
    def __init__(self, script):
        self.script = list(script)
        self.cycle_contexts_seen = []
        self.calls = 0

    def divide(self, task, client, chained_context=None, failure_context=None, cycle_context=None, model=None):
        self.cycle_contexts_seen.append(cycle_context)
        self.calls += 1
        return self.script.pop(0)


def _cyclic_division() -> DivisionResult:
    # 0 <-> 1
    return DivisionResult(is_atomic=False, sub_tasks=[
        SubTaskSpec(description="alpha", depends_on_indices=[1]),
        SubTaskSpec(description="beta", depends_on_indices=[0]),
    ])


def _acyclic_division() -> DivisionResult:
    # 0 -> 1 (linéaire)
    return DivisionResult(is_atomic=False, sub_tasks=[
        SubTaskSpec(description="alpha", depends_on_indices=[]),
        SubTaskSpec(description="beta", depends_on_indices=[0]),
    ])


def _ctx(divider, agents, tracer=None) -> RunContext:
    return RunContext(
        agents=agents, provider=SimpleNamespace(),
        divider=divider,
        aggregator=SimpleNamespace(),
        tagger=SimpleNamespace(tag=lambda desc, agents, provider, model=None: {"python"}),
        tracer=tracer,
    )


def _root() -> Task:
    return Task(description="parent", required_tags={"python": 60})


class TestRetryOnCycle:
    def test_first_cyclic_then_acyclic_recovers(self):
        a = make_agent()
        divider = _ScriptedDivider([_cyclic_division(), _acyclic_division()])
        ctx = _ctx(divider, [a])
        with patch.object(Agent, "claim", _claim_for(a)):
            with patch.object(Agent, "execute", _execute):
                result = runner._divide_and_recover(
                    _root(), ctx, depth=0, chained_context=None,
                    failure_context=None,
                    atomic_fallback=DispatchResult(status="unassigned", agent_id=None, reason="x"),
                )
        # divider appelé deux fois : initial cyclique + retry
        assert divider.calls == 2
        # le retry a reçu un cycle_context nommant les indices
        assert divider.cycle_contexts_seen[0] is None
        assert divider.cycle_contexts_seen[1] is not None
        # run récupéré : un Output (court-circuit 1 sink ou agrégat)
        assert isinstance(result, Output)

    def test_two_cyclic_divides_contained_error(self):
        a = make_agent()
        divider = _ScriptedDivider([_cyclic_division(), _cyclic_division()])
        ctx = _ctx(divider, [a])
        with patch.object(Agent, "claim", _claim_for(a)):
            with patch.object(Agent, "execute", _execute):
                result = runner._divide_and_recover(
                    _root(), ctx, depth=0, chained_context=None,
                    failure_context=None,
                    atomic_fallback=DispatchResult(status="unassigned", agent_id=None, reason="x"),
                )
        # exactement deux divides : pas de boucle infinie
        assert divider.calls == 2
        # erreur contenue, pas de ValueError propagée
        assert isinstance(result, DispatchResult)
        assert result.status == "execution_failed"

    def test_no_cycle_no_retry(self):
        a = make_agent()
        divider = _ScriptedDivider([_acyclic_division()])
        ctx = _ctx(divider, [a])
        with patch.object(Agent, "claim", _claim_for(a)):
            with patch.object(Agent, "execute", _execute):
                result = runner._divide_and_recover(
                    _root(), ctx, depth=0, chained_context=None,
                    failure_context=None,
                    atomic_fallback=DispatchResult(status="unassigned", agent_id=None, reason="x"),
                )
        assert divider.calls == 1
        assert isinstance(result, Output)

    def test_cycle_event_traced_with_raw_indices(self):
        a = make_agent()
        divider = _ScriptedDivider([_cyclic_division(), _acyclic_division()])
        tracer = Tracer("s")
        ctx = _ctx(divider, [a], tracer=tracer)
        with patch.object(Agent, "claim", _claim_for(a)):
            with patch.object(Agent, "execute", _execute):
                runner._divide_and_recover(
                    _root(), ctx, depth=0, chained_context=None,
                    failure_context=None,
                    atomic_fallback=DispatchResult(status="unassigned", agent_id=None, reason="x"),
                )
        cycle_events = [e for e in tracer.events if isinstance(e, DividerCycleEvent)]
        assert len(cycle_events) == 1
        ev = cycle_events[0]
        # le payload divider brut (indices) est conservé sur l'event
        assert set(ev.cycle_indices) == {0, 1}
        assert ev.depends_on_indices == [[1], [0]]
        assert ev.retried is True

    def test_second_cycle_event_marks_not_retried(self):
        a = make_agent()
        divider = _ScriptedDivider([_cyclic_division(), _cyclic_division()])
        tracer = Tracer("s")
        ctx = _ctx(divider, [a], tracer=tracer)
        with patch.object(Agent, "claim", _claim_for(a)):
            with patch.object(Agent, "execute", _execute):
                runner._divide_and_recover(
                    _root(), ctx, depth=0, chained_context=None,
                    failure_context=None,
                    atomic_fallback=DispatchResult(status="unassigned", agent_id=None, reason="x"),
                )
        cycle_events = [e for e in tracer.events if isinstance(e, DividerCycleEvent)]
        # deux events : le premier déclenche un retry, le second non
        assert len(cycle_events) == 2
        assert cycle_events[0].retried is True
        assert cycle_events[1].retried is False
