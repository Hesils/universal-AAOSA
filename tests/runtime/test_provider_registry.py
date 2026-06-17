import pytest

import aaosa.runtime.provider_registry as pr_mod
from aaosa.runtime.provider_registry import build_provider_registry


def _agent(name, provider=None):
    from aaosa.core.agent import Agent
    return Agent(name=name, tags_with_elo={"x": 1500}, system_prompt="p", provider=provider)


def test_registry_has_default_even_without_agent_providers(monkeypatch):
    monkeypatch.setattr(pr_mod, "create_provider", lambda name: f"prov:{name}")
    default, registry = build_provider_registry([_agent("a"), _agent("b")], default_provider="ollama")
    assert set(registry) == {"ollama"}
    assert default == "prov:ollama"


def test_registry_collects_distinct_agent_providers(monkeypatch):
    monkeypatch.setattr(pr_mod, "create_provider", lambda name: f"prov:{name}")
    agents = [_agent("a", "openai"), _agent("b", "ollama"), _agent("c", "openai")]
    default, registry = build_provider_registry(agents, default_provider="ollama")
    assert set(registry) == {"ollama", "openai"}
    assert default == "prov:ollama"


def test_unknown_provider_name_propagates(monkeypatch):
    def boom(name):
        raise ValueError(f"Unknown provider: {name!r}")
    monkeypatch.setattr(pr_mod, "create_provider", boom)
    with pytest.raises(ValueError, match="Unknown provider"):
        build_provider_registry([_agent("a", "weird")])
