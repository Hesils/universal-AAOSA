"""Tests for per-agent provider registry resolution in run_task.

Fork #2 (d6i) : un agent portant `agent.provider="ollama"` doit être exécuté avec
le provider correspondant issu du registre, et non avec le provider par défaut du run.
Rétrocompat : provider_registry=None (défaut) ou agent.provider absent → provider par
défaut utilisé, comportement identique à avant Task 6.
"""

from unittest.mock import MagicMock, patch

import pytest

from aaosa.claiming.dispatch import DispatchResult
from aaosa.core.agent import Agent
from aaosa.runtime.providers import LLMProvider
from aaosa.runtime.runner import run_task
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
