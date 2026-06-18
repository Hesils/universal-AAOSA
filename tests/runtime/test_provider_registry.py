import pytest

import aaosa.runtime.provider_registry as pr_mod
from aaosa.runtime.provider_registry import build_provider_registry, resolve_provider
from aaosa.config.role_providers import RoleProvider, RoleProviders


def _agent(name, provider=None):
    from aaosa.core.agent import Agent
    return Agent(name=name, tags_with_elo={"x": 1500}, system_prompt="p", provider=provider)


# ---------------------------------------------------------------------------
# resolve_provider — 4 cases
# ---------------------------------------------------------------------------

def test_resolve_provider_name_registry_hit():
    """name present in registry → return matching provider."""
    prov_a = object()
    prov_b = object()
    registry = {"openai": prov_a, "ollama": prov_b}
    result = resolve_provider("openai", registry, prov_b)
    assert result is prov_a


def test_resolve_provider_name_registry_miss_returns_default():
    """name absent from registry → return default (no error)."""
    default = object()
    registry = {"ollama": object()}
    result = resolve_provider("openai", registry, default)
    assert result is default


def test_resolve_provider_name_without_registry_returns_default():
    """registry is None → return default regardless of name."""
    default = object()
    result = resolve_provider("openai", None, default)
    assert result is default


def test_resolve_provider_name_none_returns_default():
    """name is None (falsy) → return default."""
    default = object()
    registry = {"openai": object()}
    result = resolve_provider(None, registry, default)
    assert result is default


# ---------------------------------------------------------------------------
# build_provider_registry — existing tests (preserved)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# build_provider_registry — roles param
# ---------------------------------------------------------------------------

def test_registry_includes_role_provider_absent_from_agents(monkeypatch):
    """A provider named only in RoleProviders (not in agents) must land in registry."""
    monkeypatch.setattr(pr_mod, "create_provider", lambda name: f"prov:{name}")
    # Only agent uses "ollama", but divider role targets "openai"
    roles = RoleProviders(divider=RoleProvider(provider="openai"))
    default, registry = build_provider_registry(
        [_agent("a")], default_provider="ollama", roles=roles
    )
    assert "openai" in registry
    assert "ollama" in registry
    assert default == "prov:ollama"


def test_registry_roles_none_unchanged(monkeypatch):
    """roles=None → same behaviour as before (no extra providers)."""
    monkeypatch.setattr(pr_mod, "create_provider", lambda name: f"prov:{name}")
    default, registry = build_provider_registry([_agent("a")], default_provider="ollama", roles=None)
    assert set(registry) == {"ollama"}


def test_registry_roles_provider_none_not_added(monkeypatch):
    """RoleProvider with provider=None contributes nothing to the name set."""
    monkeypatch.setattr(pr_mod, "create_provider", lambda name: f"prov:{name}")
    roles = RoleProviders(divider=RoleProvider(provider=None))
    default, registry = build_provider_registry([_agent("a")], default_provider="ollama", roles=roles)
    assert set(registry) == {"ollama"}
