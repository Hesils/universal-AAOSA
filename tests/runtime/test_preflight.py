import pytest

from aaosa.config.role_providers import RoleProvider, RoleProviders
from aaosa.core.agent import Agent
from aaosa.runtime.preflight import PreflightError, preflight_models
from aaosa.runtime.providers import ProviderUnreachableError


class _FakeProvider:
    def __init__(self, default_model: str, available: set[str] | None = None, unreachable: bool = False):
        self._default_model = default_model
        self._available = available if available is not None else {default_model}
        self._unreachable = unreachable

    @property
    def default_model(self) -> str:
        return self._default_model

    def available_models(self) -> set[str]:
        if self._unreachable:
            raise ProviderUnreachableError("down")
        return self._available


def _agent(name: str, provider=None, model=None) -> Agent:
    return Agent(
        name=name,
        tags_with_elo={"test": 50},
        system_prompt="Test agent.",
        provider=provider,
        model=model,
    )


def test_all_models_available_passes():
    registry = {"ollama": _FakeProvider("qwen3:4b", {"qwen3:4b", "llama3:8b"})}
    agents = [_agent("a", model="qwen3:4b"), _agent("b")]  # b -> défaut qwen3:4b
    preflight_models(agents, RoleProviders(), registry, "ollama")  # ne lève pas


def test_missing_agent_model_raises_with_name_and_model():
    registry = {"ollama": _FakeProvider("qwen3:4b", {"qwen3:4b"})}
    agents = [_agent("alice", model="absent:99b")]
    with pytest.raises(PreflightError) as exc:
        preflight_models(agents, RoleProviders(), registry, "ollama")
    msg = str(exc.value)
    assert "alice" in msg and "absent:99b" in msg and "ollama" in msg


def test_missing_role_model_raises():
    registry = {"ollama": _FakeProvider("qwen3:4b", {"qwen3:4b"})}
    roles = RoleProviders(divider=RoleProvider(model="ghost:7b"))
    with pytest.raises(PreflightError) as exc:
        preflight_models([_agent("a")], roles, registry, "ollama")
    assert "divider" in str(exc.value) and "ghost:7b" in str(exc.value)


def test_unreachable_provider_raises():
    registry = {"openai": _FakeProvider("gpt-4o-mini", unreachable=True)}
    agents = [_agent("a", provider="openai", model="gpt-4o-mini")]
    with pytest.raises(PreflightError) as exc:
        preflight_models(agents, RoleProviders(), registry, "openai")
    assert "openai" in str(exc.value) and "injoignable" in str(exc.value).lower()


def test_aggregates_all_problems_in_one_message():
    registry = {"ollama": _FakeProvider("qwen3:4b", {"qwen3:4b"})}
    agents = [_agent("a", model="x:1"), _agent("b", model="y:2")]
    with pytest.raises(PreflightError) as exc:
        preflight_models(agents, RoleProviders(), registry, "ollama")
    msg = str(exc.value)
    assert "x:1" in msg and "y:2" in msg  # les deux, pas fail-fast


def test_queries_each_provider_once(monkeypatch):
    calls = {"n": 0}
    prov = _FakeProvider("qwen3:4b", {"qwen3:4b"})
    orig = prov.available_models

    def counting():
        calls["n"] += 1
        return orig()

    prov.available_models = counting
    registry = {"ollama": prov}
    agents = [_agent("a"), _agent("b"), _agent("c")]
    preflight_models(agents, RoleProviders(), registry, "ollama")
    assert calls["n"] == 1  # un seul appel réseau par provider distinct
