"""Tests for per-agent provider registry resolution in run_task.

Fork #2 (d6i) : un agent portant `agent.provider="ollama"` doit être exécuté avec
le provider correspondant issu du registre, et non avec le provider par défaut du run.
Rétrocompat : provider_registry=None (défaut) ou agent.provider absent → provider par
défaut utilisé, comportement identique à avant Task 6.

Task 6 review fix : provider_registry doit être porté par RunContext et propagé via
run_chain et _retry_with_consignes.
"""

from unittest.mock import MagicMock, patch

import pytest

from aaosa.claiming.dispatch import DispatchResult
from aaosa.core.agent import Agent
from aaosa.qa.protocol import QAEvaluator, QAResult
from aaosa.runtime.context import RunContext
from aaosa.runtime.divider import DivisionResult, SubTaskSpec
from aaosa.runtime.providers import LLMProvider
from aaosa.runtime.runner import run_chain, run_task
from aaosa.schemas.claim import Claim
from aaosa.schemas.output import LLMMetadata, Output
from aaosa.schemas.task import Task


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(content: str = "done"):
    """Fake ChatCompletion-like object accepted by agent.execute (no-tools path)."""
    choice = MagicMock()
    choice.finish_reason = "stop"
    choice.message.content = content
    choice.message.tool_calls = None

    usage = MagicMock()
    usage.prompt_tokens = 5
    usage.completion_tokens = 3

    response = MagicMock()
    response.choices = [choice]
    response.usage = usage
    response.model = "test-model"
    return response


def _make_provider_mock(name: str = "mock") -> MagicMock:
    """MagicMock(spec=LLMProvider) câblé pour que agent.execute réussisse."""
    m = MagicMock(spec=LLMProvider)
    m.complete.return_value = _make_response()
    # parse n'est pas appelé dans execute (seulement dans claim)
    return m


def _make_agent_with_provider(provider_name: str | None = None, elo: int = 80) -> Agent:
    return Agent(
        name="AgentX",
        tags_with_elo={"python": elo},
        system_prompt="You are AgentX.",
        provider=provider_name,
    )


def _make_task() -> Task:
    return Task(
        description="Write a function",
        required_tags={"python": 60},
    )


def _make_claim(agent: Agent, task: Task) -> Claim:
    return Claim(
        agent_id=agent.id,
        task_id=task.id,
        decision="claim",
        justification="fits",
    )


# ---------------------------------------------------------------------------
# Test 1 : agent.provider="ollama" + registre → ollama_mock appelé
# ---------------------------------------------------------------------------

def test_agent_with_named_provider_uses_registry():
    """Un agent portant provider='ollama' exécuté avec un registre {"ollama": ollama_mock}
    doit appeler ollama_mock.complete, PAS default_mock.complete."""
    default_mock = _make_provider_mock("default")
    ollama_mock = _make_provider_mock("ollama")

    agent = _make_agent_with_provider("ollama")
    task = _make_task()
    claim = _make_claim(agent, task)

    with patch.object(Agent, "claim", return_value=claim):
        result = run_task(
            task,
            [agent],
            default_mock,
            provider_registry={"ollama": ollama_mock},
        )

    assert isinstance(result, Output), f"expected Output, got {result!r}"
    # Le provider ollama_mock doit avoir servi l'exécution
    assert ollama_mock.complete.called, "ollama_mock.complete should have been called"
    # Le provider par défaut NE doit PAS avoir servi execute (il peut servir claim via run_phase2)
    # On vérifie que complete sur default_mock n'a PAS été appelé lors de l'execute
    # (claim utilise parse, pas complete — donc default_mock.complete doit rester à 0)
    assert not default_mock.complete.called, "default_mock.complete should NOT have been called"


# ---------------------------------------------------------------------------
# Test 2 : agent sans provider → provider par défaut utilisé (rétrocompat)
# ---------------------------------------------------------------------------

def test_agent_without_named_provider_uses_default():
    """Un agent sans provider (agent.provider=None) → execute avec le provider par défaut."""
    default_mock = _make_provider_mock("default")
    ollama_mock = _make_provider_mock("ollama")

    agent = _make_agent_with_provider(None)   # pas de provider spécifique
    task = _make_task()
    claim = _make_claim(agent, task)

    with patch.object(Agent, "claim", return_value=claim):
        result = run_task(
            task,
            [agent],
            default_mock,
            provider_registry={"ollama": ollama_mock},
        )

    assert isinstance(result, Output), f"expected Output, got {result!r}"
    assert default_mock.complete.called, "default_mock.complete should have been called"
    assert not ollama_mock.complete.called, "ollama_mock.complete should NOT have been called"


# ---------------------------------------------------------------------------
# Test 3 : agent.provider non trouvé dans le registre → fallback default
# ---------------------------------------------------------------------------

def test_agent_provider_not_in_registry_falls_back_to_default():
    """Si agent.provider est renseigné mais absent du registre → fallback default_mock."""
    default_mock = _make_provider_mock("default")

    agent = _make_agent_with_provider("gemini")   # absent du registre
    task = _make_task()
    claim = _make_claim(agent, task)

    with patch.object(Agent, "claim", return_value=claim):
        result = run_task(
            task,
            [agent],
            default_mock,
            provider_registry={"ollama": MagicMock(spec=LLMProvider)},  # gemini absent
        )

    assert isinstance(result, Output), f"expected Output, got {result!r}"
    assert default_mock.complete.called, "default_mock.complete should have been called (fallback)"


# ---------------------------------------------------------------------------
# Test 4 : provider_registry=None (défaut) → comportement identique à avant
# ---------------------------------------------------------------------------

def test_no_registry_uses_default_provider():
    """Rétrocompat pure : provider_registry=None → default_mock utilisé."""
    default_mock = _make_provider_mock("default")

    agent = _make_agent_with_provider("ollama")  # provider renseigné mais pas de registre
    task = _make_task()
    claim = _make_claim(agent, task)

    with patch.object(Agent, "claim", return_value=claim):
        result = run_task(task, [agent], default_mock)  # pas de provider_registry

    assert isinstance(result, Output), f"expected Output, got {result!r}"
    assert default_mock.complete.called, "default_mock.complete should have been called"


# ---------------------------------------------------------------------------
# Helpers pour les tests de propagation (RunContext + run_chain + retry)
# ---------------------------------------------------------------------------

class _FakeTagger:
    def __init__(self, default=("python",)):
        self.default = set(default)

    def tag(self, description, agents, provider, model=None):
        return set(self.default)


class _StaticDivider:
    def __init__(self, division):
        self.division = division

    def divide(self, task, provider, chained_context=None, failure_context=None, cycle_context=None, model=None):
        return self.division


class _RecordingAggregator:
    def aggregate(self, parent_task, sub_outputs, provider, tracer=None, model=None):
        from aaosa.schemas.output import LLMMetadata, Output
        return Output(
            task_id=parent_task.id, agent_id="aggregator", content="agg",
            llm_metadata=LLMMetadata(model_name="m", tokens_in=1, tokens_out=1, latency_ms=1.0),
        )


def _make_run_context(
    agent: Agent,
    default_provider: LLMProvider,
    provider_registry: dict[str, LLMProvider] | None = None,
    evaluator: QAEvaluator | None = None,
) -> RunContext:
    return RunContext(
        agents=[agent],
        provider=default_provider,
        divider=_StaticDivider(DivisionResult(sub_tasks=[SubTaskSpec(description="sub")])),
        aggregator=_RecordingAggregator(),
        tagger=_FakeTagger(),
        provider_registry=provider_registry,
        evaluator=evaluator,
    )


# ---------------------------------------------------------------------------
# Test 5 : run_chain threads provider_registry to run_task via RunContext
# ---------------------------------------------------------------------------

def test_run_chain_threads_registry_to_agent():
    """Un agent avec provider='ollama' dans une sous-tâche exécutée via run_chain
    doit utiliser ollama_mock, pas default_mock.

    Prouve que provider_registry est porté par RunContext et accessible à run_task
    dans la boucle run_chain → run_with_recovery → run_task.
    """
    default_mock = _make_provider_mock("default")
    ollama_mock = _make_provider_mock("ollama")

    agent = _make_agent_with_provider("ollama", elo=80)
    task = Task(description="sub", required_tags={"python": 60})
    claim = _make_claim(agent, task)

    ctx = _make_run_context(agent, default_mock, provider_registry={"ollama": ollama_mock})

    with patch.object(Agent, "claim", return_value=claim):
        outputs = run_chain([task], ctx, depth=0)

    assert task.id in outputs, f"expected task to succeed, outputs={outputs}"
    assert ollama_mock.complete.called, "ollama_mock.complete should have been called via run_chain"
    assert not default_mock.complete.called, "default_mock.complete should NOT have been called"


# ---------------------------------------------------------------------------
# Test 6 : _retry_with_consignes forwards registry (QA failure → retry)
# ---------------------------------------------------------------------------

class _FailOnceThenPassEvaluator:
    """QAEvaluator qui échoue une fois (le run initial), réussit la seconde (le retry).

    La première évaluation renvoie un QAResult échec → déclenche diagnostic → _retry_with_consignes.
    Le diagnostic DOIT attribuer à 'agent' pour que _retry_with_consignes soit appelé.
    On bypasse diagnose_failure pour forcer ce chemin.
    """
    def __init__(self):
        self._calls = 0

    def evaluate(self, task, output):
        self._calls += 1
        if self._calls == 1:
            return QAResult(
                task_id=task.id,
                agent_id=output.agent_id,
                success=False, score=0.2,
                reason="bad", criteria_results={},
            )
        return QAResult(
            task_id=task.id,
            agent_id=output.agent_id,
            success=True, score=0.9,
            reason="ok", criteria_results={},
        )


def test_retry_path_forwards_registry():
    """Un agent avec provider='ollama' qui échoue QA et est retenté via
    _retry_with_consignes doit utiliser ollama_mock sur le retry, pas default_mock.

    Prouve que ctx.provider_registry est bien propagé dans _retry_with_consignes.
    """
    from aaosa.qa.diagnostic import DiagnosticResult
    from aaosa.runtime.runner import run_with_recovery

    default_mock = _make_provider_mock("default")
    ollama_mock = _make_provider_mock("ollama")

    agent = _make_agent_with_provider("ollama", elo=80)
    task = Task(description="write a function", required_tags={"python": 60})
    claim = _make_claim(agent, task)

    evaluator = _FailOnceThenPassEvaluator()
    ctx = _make_run_context(
        agent, default_mock,
        provider_registry={"ollama": ollama_mock},
        evaluator=evaluator,
    )

    # Force diagnose_failure to return attribution="agent" so _retry_with_consignes is called.
    diag = DiagnosticResult(attribution="agent", reason="bad output", consignes="fix it")
    with patch.object(Agent, "claim", return_value=claim):
        with patch("aaosa.runtime.runner.diagnose_failure", return_value=diag):
            result = run_with_recovery(task, ctx, depth=0)

    assert isinstance(result, Output), f"expected Output on retry success, got {result!r}"
    # ollama_mock.complete must have been called at least twice (initial run + retry)
    assert ollama_mock.complete.call_count >= 2, (
        f"ollama_mock.complete should have been called ≥2 times (got {ollama_mock.complete.call_count}); "
        "if it's 0 the registry was not forwarded"
    )
    assert not default_mock.complete.called, "default_mock.complete should NOT have been called"
